"""Databricks integration API (FR-6).

Endpoints:
  POST /api/v1/databricks/webhook       — Databricks job failure webhook
  POST /api/v1/databricks/runs/context  — fetch failure context (step 2)
  POST /api/v1/investigate              — DeployGuard investigation (step 3)

Automated webhook flow (async):
  webhook -> extract run_id -> runs/context -> to_investigate_request -> investigate
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.api.investigate import execute_investigation
from app.config import Settings, get_settings
from app.core.cache import TTLCache
from app.core.logging_config import get_logger
from app.dependencies import (
    get_bedrock_client,
    get_databricks_client,
    get_dedup_cache,
    get_jira_client,
    get_postgres_store,
    get_s3_store,
    get_settings_dep,
    get_slack_client,
)
from app.models.schemas import (
    DatabricksInvestigateRequest,
    DatabricksRunContextRequest,
    DatabricksRunContextResponse,
    DatabricksWebhookPayload,
    DatabricksWebhookResponse,
    InvestigateResponse,
    Severity,
)
from app.services.bedrock import BedrockAgentClient
from app.services.databricks import DatabricksClient, DatabricksError
from app.services.jira import JiraClient
from app.services.postgres_store import PostgresIncidentStore
from app.services.s3_store import S3IncidentStore
from app.services.slack import SlackClient

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/databricks")

DATABRICKS_SERVICE = "Databricks"


def _fetch_run_context(
    payload: DatabricksRunContextRequest,
    databricks_client: DatabricksClient,
) -> DatabricksRunContextResponse:
    """Shared logic for POST /api/v1/databricks/runs/context."""
    try:
        failure = databricks_client.get_failure_context(payload.run_id)
        job_id = databricks_client.resolve_job_id(payload.run_id, payload.job_id)
    except DatabricksError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return DatabricksRunContextResponse(
        run_id=payload.run_id,
        job_id=job_id,
        error_message=failure["error_message"],
        stack_trace=failure.get("stack_trace"),
        log_snippet=failure.get("log_snippet"),
        task_name=failure.get("task_name"),
        notebook_name=failure.get("notebook_name"),
        notebook_context=failure.get("notebook_context"),
    )


async def _context_to_investigation(
    context_request: DatabricksRunContextRequest,
    *,
    service: str,
    environment: str,
    request: Request,
    settings: Settings,
    databricks_client: DatabricksClient,
    bedrock_client: BedrockAgentClient,
    jira_client: JiraClient,
    slack_client: SlackClient,
    s3_store: S3IncidentStore,
    postgres_store: Optional[PostgresIncidentStore],
    cache: TTLCache,
    task_name: Optional[str] = None,
    severity: Optional[Severity] = None,
) -> InvestigateResponse:
    """Step 2 (context) -> step 3 (investigate)."""
    context = _fetch_run_context(context_request, databricks_client)
    if task_name:
        context = context.model_copy(update={"task_name": task_name})

    investigate_payload = context.to_investigate_request(
        service=service,
        environment=environment,
        severity=severity,
    )
    return await execute_investigation(
        investigate_payload,
        request,
        settings,
        bedrock_client,
        jira_client,
        slack_client,
        s3_store,
        postgres_store,
        cache,
    )


async def _execute_databricks_investigation(
    payload: DatabricksInvestigateRequest,
    request: Request,
    settings: Settings,
    databricks_client: DatabricksClient,
    bedrock_client: BedrockAgentClient,
    jira_client: JiraClient,
    slack_client: SlackClient,
    s3_store: S3IncidentStore,
    postgres_store: Optional[PostgresIncidentStore],
    cache: TTLCache,
) -> InvestigateResponse:
    context_request = DatabricksRunContextRequest(run_id=payload.run_id, job_id=payload.job_id)
    return await _context_to_investigation(
        context_request,
        service=DATABRICKS_SERVICE,
        environment=payload.environment,
        request=request,
        settings=settings,
        databricks_client=databricks_client,
        bedrock_client=bedrock_client,
        jira_client=jira_client,
        slack_client=slack_client,
        s3_store=s3_store,
        postgres_store=postgres_store,
        cache=cache,
        task_name=payload.task_name,
        severity=payload.severity,
    )


async def _run_webhook_pipeline(request: Request, webhook: DatabricksWebhookPayload) -> None:
    """Webhook run_id -> context API -> investigate API (background)."""
    settings = get_settings()
    run_id = webhook.extract_run_id()
    context_request = webhook.to_context_request()
    task_name = webhook.task.task_key if webhook.task else None

    try:
        response = await _context_to_investigation(
            context_request,
            service=DATABRICKS_SERVICE,
            environment=settings.databricks_default_environment,
            request=request,
            settings=settings,
            databricks_client=request.app.state.databricks_client,
            bedrock_client=request.app.state.bedrock_client,
            jira_client=request.app.state.jira_client,
            slack_client=request.app.state.slack_client,
            s3_store=request.app.state.s3_store,
            postgres_store=getattr(request.app.state, "postgres_store", None),
            cache=request.app.state.dedup_cache,
            task_name=task_name,
        )
        logger.info(
            "databricks_webhook_pipeline_complete",
            extra={
                "run_id": run_id,
                "investigation_id": response.investigation_id,
                "status": response.status,
            },
        )
    except Exception:
        logger.exception("databricks_webhook_pipeline_failed", extra={"run_id": run_id})


@router.post("/webhook", response_model=DatabricksWebhookResponse, status_code=202)
async def databricks_job_webhook(
    payload: DatabricksWebhookPayload,
    background_tasks: BackgroundTasks,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> DatabricksWebhookResponse:
    """Accept Databricks failure webhook, return run_id, then run context -> investigate async."""
    if not settings.enable_databricks:
        raise HTTPException(status_code=503, detail="Databricks integration is disabled")

    if payload.event_type != "jobs.on_failure":
        return DatabricksWebhookResponse(
            status="ignored",
            event_type=payload.event_type,
            detail="Only jobs.on_failure triggers investigation",
        )

    run_id = payload.extract_run_id()
    background_tasks.add_task(_run_webhook_pipeline, request, payload)
    logger.info("databricks_webhook_accepted", extra={"run_id": run_id, "job_name": payload.job.name})
    return DatabricksWebhookResponse(
        status="accepted",
        run_id=run_id,
        event_type=payload.event_type,
        detail="run_id queued for context + investigate pipeline",
    )


@router.post("/runs/context", response_model=DatabricksRunContextResponse)
async def get_run_context(
    payload: DatabricksRunContextRequest,
    settings: Settings = Depends(get_settings_dep),
    databricks_client: DatabricksClient = Depends(get_databricks_client),
) -> DatabricksRunContextResponse:
    if not settings.enable_databricks:
        raise HTTPException(status_code=503, detail="Databricks integration is disabled")
    return _fetch_run_context(payload, databricks_client)


@router.post("/investigate", response_model=InvestigateResponse)
async def investigate_from_databricks_run(
    payload: DatabricksInvestigateRequest,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    databricks_client: DatabricksClient = Depends(get_databricks_client),
    bedrock_client: BedrockAgentClient = Depends(get_bedrock_client),
    jira_client: JiraClient = Depends(get_jira_client),
    slack_client: SlackClient = Depends(get_slack_client),
    s3_store: S3IncidentStore = Depends(get_s3_store),
    postgres_store: Optional[PostgresIncidentStore] = Depends(get_postgres_store),
    cache: TTLCache = Depends(get_dedup_cache),
) -> InvestigateResponse:
    """Automated: context API -> to_investigate_request -> DeployGuard."""
    if not settings.enable_databricks:
        raise HTTPException(status_code=503, detail="Databricks integration is disabled")

    return await _execute_databricks_investigation(
        payload,
        request,
        settings,
        databricks_client,
        bedrock_client,
        jira_client,
        slack_client,
        s3_store,
        postgres_store,
        cache,
    )
