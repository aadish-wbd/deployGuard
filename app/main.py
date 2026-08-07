"""DeployGuard FastAPI application entrypoint.

Run with: uvicorn app.main:app --host 0.0.0.0 --port 8000
See RUNBOOK.md for full setup and demo instructions.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import dashboard, databricks, health, incidents, investigate
from app.config import get_settings
from app.core.cache import TTLCache
from app.core.env_debug import print_loaded_config
from app.core.logging_config import configure_logging, get_logger
from app.core.rate_limit import DailyCap
from app.services.bedrock import BedrockAgentClient
from app.services.databricks import DatabricksClient
from app.services.github import GitHubClient
from app.services.jira import JiraClient, validate_jira_config
from app.services.postgres_store import PostgresIncidentStore
from app.services.s3_store import S3IncidentStore
from app.services.secrets import load_database_secret_into_env, load_secrets_into_env
from app.services.slack import SlackClient

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    secret_id = settings.secrets_manager_secret_arn or settings.secrets_manager_secret_name
    secrets_loaded = False
    if secret_id:
        loaded = load_secrets_into_env(secret_id, settings.aws_region)
        secrets_loaded = bool(loaded)
        get_settings.cache_clear()
        settings = get_settings()

    if settings.database_secret_name:
        load_database_secret_into_env(settings.database_secret_name, settings.aws_region)
        get_settings.cache_clear()
        settings = get_settings()

    print_loaded_config(settings, secrets_loaded=secrets_loaded, secret_id=secret_id)
    validate_jira_config(settings)

    app.state.jira_client = JiraClient(settings)
    app.state.slack_client = SlackClient(settings)
    app.state.github_client = GitHubClient(settings)
    app.state.bedrock_client = BedrockAgentClient(
        settings,
        jira_client=app.state.jira_client,
        slack_client=app.state.slack_client,
        github_client=app.state.github_client,
    )
    app.state.s3_store = S3IncidentStore(settings)
    app.state.postgres_store = PostgresIncidentStore(settings) if settings.postgres_enabled else None
    app.state.databricks_client = DatabricksClient(settings)
    app.state.dedup_cache = TTLCache(settings.dedup_cache_ttl_seconds)
    app.state.daily_cap = DailyCap(settings.daily_investigation_cap)

    logger.info(
        "deployguard_startup",
        extra={
            "region": settings.aws_region,
            "s3_bucket": settings.s3_bucket,
            "postgres_enabled": settings.postgres_enabled,
        },
    )
    yield
    if app.state.postgres_store is not None:
        app.state.postgres_store.close()
    logger.info("deployguard_shutdown")


app = FastAPI(title="DeployGuard", version="1.0.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(investigate.router)
app.include_router(databricks.router)
app.include_router(incidents.router)
app.include_router(dashboard.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    if "databricks/webhook" in request.url.path:
        try:
            body = (await request.body()).decode("utf-8", errors="replace")
        except Exception:
            body = "(unreadable)"
        logger.warning(
            "databricks_webhook_validation_failed",
            extra={"body": body[:4000], "errors": exc.errors()},
        )
    return JSONResponse(status_code=400, content={"detail": exc.errors()})


_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _mount_dashboard_ui() -> None:
    if not _FRONTEND_DIST.is_dir():
        logger.warning("frontend_dist_missing", extra={"path": str(_FRONTEND_DIST)})
        return

    assets_dir = _FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="dashboard-assets")

    @app.get("/", include_in_schema=False)
    async def dashboard_root() -> FileResponse:
        return FileResponse(_FRONTEND_DIST / "index.html")

    @app.get("/{spa_path:path}", include_in_schema=False)
    async def dashboard_spa(spa_path: str) -> FileResponse:
        if spa_path.startswith(("api/", "docs", "redoc", "openapi.json")):
            raise HTTPException(status_code=404)
        candidate = _FRONTEND_DIST / spa_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")


_mount_dashboard_ui()
