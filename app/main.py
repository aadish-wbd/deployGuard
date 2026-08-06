"""DeployGuard FastAPI application entrypoint.

Run with: uvicorn app.main:app --host 0.0.0.0 --port 8000
See RUNBOOK.md for full setup and demo instructions.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import health, incidents, investigate
from app.config import get_settings
from app.core.cache import TTLCache
from app.core.logging_config import configure_logging, get_logger
from app.core.rate_limit import DailyCap
from app.services.bedrock import BedrockAgentClient
from app.services.jira import JiraClient
from app.services.s3_store import S3IncidentStore
from app.services.secrets import load_secrets_into_env
from app.services.slack import SlackClient

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    if settings.secrets_manager_secret_name:
        load_secrets_into_env(settings.secrets_manager_secret_name, settings.aws_region)
        get_settings.cache_clear()
        settings = get_settings()

    app.state.jira_client = JiraClient(settings)
    app.state.slack_client = SlackClient(settings)
    app.state.bedrock_client = BedrockAgentClient(
        settings,
        jira_client=app.state.jira_client,
        slack_client=app.state.slack_client,
    )
    app.state.s3_store = S3IncidentStore(settings)
    app.state.dedup_cache = TTLCache(settings.dedup_cache_ttl_seconds)
    app.state.daily_cap = DailyCap(settings.daily_investigation_cap)

    logger.info("deployguard_startup", extra={"region": settings.aws_region, "s3_bucket": settings.s3_bucket})
    yield
    logger.info("deployguard_shutdown")


app = FastAPI(title="DeployGuard", version="1.0.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(investigate.router)
app.include_router(incidents.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": exc.errors()})
