"""GET /health (FR-7) — service + Bedrock connectivity check."""
from typing import Optional

from fastapi import APIRouter, Depends

from app.config import Settings
from app.dependencies import get_bedrock_client, get_postgres_store, get_settings_dep
from app.models.schemas import HealthResponse
from app.services.bedrock import BedrockAgentClient
from app.services.postgres_store import PostgresIncidentStore

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(
    settings: Settings = Depends(get_settings_dep),
    bedrock_client: BedrockAgentClient = Depends(get_bedrock_client),
    postgres_store: Optional[PostgresIncidentStore] = Depends(get_postgres_store),
) -> HealthResponse:
    bedrock_ok = bedrock_client.health_check()
    postgres_ok: Optional[bool] = None
    if settings.postgres_enabled:
        postgres_ok = postgres_store.ping() if postgres_store is not None else False

    if not bedrock_ok:
        detail = "Bedrock agent unreachable"
    elif postgres_ok is False:
        detail = "PostgreSQL unreachable"
    else:
        detail = None

    overall_ok = bedrock_ok and (postgres_ok is None or postgres_ok)
    return HealthResponse(
        status="ok" if overall_ok else "degraded",
        bedrock_reachable=bedrock_ok,
        postgres_reachable=postgres_ok,
        detail=detail,
    )
