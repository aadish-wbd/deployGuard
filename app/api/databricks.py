"""Databricks integration API (FR-6).

Endpoints:
  POST /api/v1/databricks/runs/context  — fetch failure context only (manual / debug)
  POST /api/v1/databricks/investigate   — automated: context -> investigate -> DeployGuard
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.investigate import execute_investigation
from app.config import Settings
from app.core.cache import TTLCache
from app.dependencies import (
    get_bedrock_client,
    get_databricks_client,
    get_dedup_cache,
    get_jira_client,
    get_s3_store,
    get_settings_dep,
    get_slack_client,
)
from app.models.schemas import (
    DatabricksInvestigateRequest,
    DatabricksRunContextRequest,
    DatabricksRunContextResponse,
    InvestigateResponse,
)
from app.services.bedrock import BedrockAgentClient
from app.services.databricks import DatabricksClient, DatabricksError
from app.services.jira import JiraClient
from app.services.s3_store import S3IncidentStore
from app.services.slack import SlackClient

router = APIRouter(prefix="/api/v1/databricks")


def _fetch_run_context(
    payload: DatabricksRunContextRequest,
    databricks_client: DatabricksClient,
) -> DatabricksRunContextResponse:
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
    cache: TTLCache = Depends(get_dedup_cache),
) -> InvestigateResponse:
    """Automated flow: Databricks export -> to_investigate_request -> DeployGuard."""
    if not settings.enable_databricks:
        raise HTTPException(status_code=503, detail="Databricks integration is disabled")

    context = _fetch_run_context(payload, databricks_client)
    if payload.task_name:
        context = context.model_copy(update={"task_name": payload.task_name})

    investigate_payload = context.to_investigate_request(
        service=payload.service,
        environment=payload.environment,
        severity=payload.severity,
    )
    return await execute_investigation(
        investigate_payload,
        request,
        settings,
        bedrock_client,
        jira_client,
        slack_client,
        s3_store,
        cache,
    )
