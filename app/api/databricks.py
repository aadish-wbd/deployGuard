"""POST /api/v1/databricks/investigate — fetch run export and investigate (FR-6).

Accepts a Databricks run_id, calls jobs/runs/export via the REST API to extract
failure context, then runs the standard DeployGuard investigation pipeline.
"""
from datetime import datetime, timezone

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
    InvestigateContext,
    InvestigateRequest,
    InvestigateResponse,
)
from app.services.bedrock import BedrockAgentClient
from app.services.databricks import DatabricksClient, DatabricksError
from app.services.jira import JiraClient
from app.services.s3_store import S3IncidentStore
from app.services.slack import SlackClient

router = APIRouter(prefix="/api/v1/databricks")


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
    if not settings.enable_databricks:
        raise HTTPException(status_code=503, detail="Databricks integration is disabled")

    try:
        failure = databricks_client.get_failure_context(payload.run_id)
        job_id = databricks_client.resolve_job_id(payload.run_id, payload.job_id)
    except DatabricksError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    task_name = payload.task_name or failure.get("task_name")

    investigate_payload = InvestigateRequest(
        error_message=failure["error_message"],
        stack_trace=failure.get("stack_trace"),
        service=payload.service,
        environment=payload.environment,
        timestamp=datetime.now(timezone.utc),
        context=InvestigateContext(
            job_id=job_id,
            run_id=payload.run_id,
            task_name=task_name,
            log_snippet=failure.get("log_snippet"),
            severity=payload.severity,
            notebook_context=failure.get("notebook_context"),
        ),
        triggered_by="databricks",
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
