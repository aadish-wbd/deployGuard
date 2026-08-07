"""POST /api/v1/investigate (FR-1) — the main investigation endpoint.

Orchestrates: payload validation -> dedup cache -> daily cap -> Bedrock analysis ->
JIRA ticket -> Slack alert -> S3 persistence -> PostgreSQL persistence (when configured).
JIRA/Slack/S3/Postgres failures are logged and flagged, never raised (NFR-7); a Bedrock failure yields a
`failed` status with error_detail instead of a 5xx (no silent failure).
"""
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from app.config import Settings
from app.core.cache import TTLCache
from app.core.logging_config import get_logger
from app.core.prompt import build_agent_input
from app.core.tokens import estimate_tokens
from app.dependencies import (
    get_bedrock_client,
    get_dedup_cache,
    get_jira_client,
    get_postgres_store,
    get_s3_store,
    get_settings_dep,
    get_slack_client,
)
from app.models.incident import IncidentMetadata, IncidentRecord
from app.models.schemas import ActionsTaken, InvestigateRequest, InvestigateResponse
from app.services.bedrock import BedrockAgentClient, BedrockInvocationError
from app.services.investigation_dedup import existing_rca_summary, find_existing_investigation
from app.services.jira import JiraClient, JiraError
from app.services.postgres_store import PostgresIncidentStore, s3_uris_for_record
from app.services.s3_store import S3IncidentStore
from app.services.slack import SlackClient, SlackError

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1")


def _response_from_existing_investigation(
    existing,
    *,
    investigation_id: str,
    cached: bool = False,
) -> InvestigateResponse:
    summary = existing.rca_summary or existing_rca_summary(existing.jira_ticket)
    return InvestigateResponse(
        investigation_id=existing.investigation_id or investigation_id,
        status="completed",
        root_cause=existing.root_cause,
        confidence=existing.confidence,
        rca_summary=summary,
        evidence=existing.evidence,
        suggested_fix=existing.suggested_fix,
        s3_report_url=existing.s3_report_url,
        actions=ActionsTaken(
            jira_ticket=existing.jira_ticket,
            jira_url=existing.jira_url,
            jira_created=False,
            jira_reused=True,
            slack_sent=False,
        ),
        existing_ticket=True,
        cached=cached,
    )


async def _parse_request(request: Request, settings: Settings) -> InvestigateRequest:
    body = await request.body()
    if len(body) > settings.max_request_body_bytes:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Request body is {len(body)} bytes, exceeds the "
                f"{settings.max_request_body_bytes}-byte limit. Trim stack_trace to the top "
                "5-10 frames and log_snippet to only lines matching the error."
            ),
        )

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc

    try:
        return InvestigateRequest.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()) from exc


@router.post("/investigate", response_model=InvestigateResponse)
async def investigate(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    bedrock_client: BedrockAgentClient = Depends(get_bedrock_client),
    jira_client: JiraClient = Depends(get_jira_client),
    slack_client: SlackClient = Depends(get_slack_client),
    s3_store: S3IncidentStore = Depends(get_s3_store),
    postgres_store: Optional[PostgresIncidentStore] = Depends(get_postgres_store),
    cache: TTLCache = Depends(get_dedup_cache),
) -> InvestigateResponse:
    payload = await _parse_request(request, settings)
    return await execute_investigation(
        payload,
        request,
        settings,
        bedrock_client,
        jira_client,
        slack_client,
        s3_store,
        postgres_store,
        cache,
    )


async def execute_investigation(
    payload: InvestigateRequest,
    request: Request,
    settings: Settings,
    bedrock_client: BedrockAgentClient,
    jira_client: JiraClient,
    slack_client: SlackClient,
    s3_store: S3IncidentStore,
    postgres_store: Optional[PostgresIncidentStore],
    cache: TTLCache,
) -> InvestigateResponse:

    cache_key = TTLCache.make_key(payload.error_message, payload.service, payload.environment)
    cached_response = cache.get(cache_key)
    if cached_response is not None:
        return cached_response.model_copy(update={"cached": True})

    existing = find_existing_investigation(
        payload,
        settings,
        jira_client=jira_client,
        postgres_store=postgres_store,
    )
    if existing is not None:
        response = _response_from_existing_investigation(
            existing,
            investigation_id=str(uuid.uuid4()),
        )
        cache.set(cache_key, response)
        logger.info(
            "investigation_existing_ticket_reused",
            extra={"jira_ticket": existing.jira_ticket, "service": payload.service},
        )
        return response.model_copy(update={"cached": False})

    daily_cap = request.app.state.daily_cap
    if not daily_cap.try_consume():
        raise HTTPException(status_code=429, detail="Daily investigation cap reached")

    investigation_id = str(uuid.uuid4())
    started_at = time.monotonic()

    input_text = build_agent_input(payload, github_default_repo=settings.github_default_repo)
    token_estimate = estimate_tokens(input_text)
    if token_estimate > settings.max_input_tokens_estimate:
        raise HTTPException(
            status_code=400,
            detail=f"Estimated input tokens ({token_estimate}) exceed the {settings.max_input_tokens_estimate} limit.",
        )

    actions = ActionsTaken()
    root_cause = confidence = rca_summary = suggested_fix = error_detail = None
    evidence: list[str] = []
    status: str = "completed"

    try:
        rca = bedrock_client.invoke(session_id=investigation_id, input_text=input_text)
        root_cause = rca.root_cause
        confidence = rca.confidence
        evidence = rca.evidence
        rca_summary = rca.rca_summary
        suggested_fix = rca.suggested_fix

        if settings.enable_jira:
            try:
                ticket_key, ticket_url = jira_client.create_ticket(payload, rca)
                actions.jira_ticket = ticket_key
                actions.jira_url = ticket_url
                actions.jira_created = True
            except JiraError:
                logger.exception("jira_create_failed", extra={"investigation_id": investigation_id})

        if settings.enable_slack:
            try:
                slack_client.send_alert(payload, rca, actions.jira_url)
                actions.slack_sent = True
            except SlackError:
                logger.exception("slack_alert_failed", extra={"investigation_id": investigation_id})

    except BedrockInvocationError as exc:
        status = "failed"
        error_detail = str(exc)
        logger.error("bedrock_investigation_failed", extra={"investigation_id": investigation_id, "error": error_detail})

    latency_ms = int((time.monotonic() - started_at) * 1000)

    record = IncidentRecord(
        investigation_id=investigation_id,
        timestamp=payload.timestamp or datetime.now(timezone.utc),
        service=payload.service,
        environment=payload.environment,
        input=payload,
        root_cause=root_cause,
        confidence=confidence,
        evidence=evidence,
        rca_summary=rca_summary,
        suggested_fix=suggested_fix,
        error_detail=error_detail,
        actions=actions,
        metadata=IncidentMetadata(
            latency_ms=latency_ms,
            token_estimate=token_estimate,
            triggered_by=payload.triggered_by,
            status=status,
        ),
    )

    s3_report_url = None
    try:
        s3_report_url = s3_store.save(record)
    except Exception:
        logger.exception("s3_persist_failed", extra={"investigation_id": investigation_id})

    if postgres_store is not None:
        s3_report_uri, rca_s3_uri = s3_uris_for_record(settings, record)
        if s3_report_url:
            s3_report_uri = s3_report_url
        try:
            postgres_store.save(record, rca_s3_uri=rca_s3_uri, s3_report_uri=s3_report_uri)
        except Exception:
            logger.exception("postgres_persist_failed", extra={"investigation_id": investigation_id})

    logger.info(
        "investigation_complete",
        extra={
            "investigation_id": investigation_id,
            "status": status,
            "latency_ms": latency_ms,
            "token_estimate": token_estimate,
        },
    )

    response = InvestigateResponse(
        investigation_id=investigation_id,
        status=status,
        root_cause=root_cause,
        confidence=confidence,
        rca_summary=rca_summary,
        evidence=evidence,
        suggested_fix=suggested_fix,
        s3_report_url=s3_report_url,
        actions=actions,
        error_detail=error_detail,
    )
    cache.set(cache_key, response)
    return response
