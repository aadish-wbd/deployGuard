"""GET /health (FR-7) — service + Bedrock connectivity check."""
from fastapi import APIRouter, Depends

from app.dependencies import get_bedrock_client
from app.models.schemas import HealthResponse
from app.services.bedrock import BedrockAgentClient

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(bedrock_client: BedrockAgentClient = Depends(get_bedrock_client)) -> HealthResponse:
    bedrock_ok = bedrock_client.health_check()
    return HealthResponse(
        status="ok" if bedrock_ok else "degraded",
        bedrock_reachable=bedrock_ok,
        detail=None if bedrock_ok else "Bedrock agent unreachable",
    )
