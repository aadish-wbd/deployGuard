"""GET /api/v1/dashboard/stats — KPI aggregates for the incidents dashboard."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import Settings
from app.dependencies import get_postgres_store, get_settings_dep
from app.models.schemas import DashboardStatsResponse
from app.services.postgres_store import PostgresIncidentStore

router = APIRouter(prefix="/api/v1/dashboard")


@router.get("/stats", response_model=DashboardStatsResponse)
def dashboard_stats(
    service: Optional[str] = Query(default=None),
    settings: Settings = Depends(get_settings_dep),
    postgres_store: Optional[PostgresIncidentStore] = Depends(get_postgres_store),
) -> DashboardStatsResponse:
    if not settings.postgres_enabled or postgres_store is None:
        raise HTTPException(status_code=503, detail="Dashboard database is not configured")

    try:
        raw = postgres_store.dashboard_stats(service=service)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Dashboard stats unavailable: {exc}") from exc

    by_service = raw.get("by_service") or {}
    by_severity = raw.get("by_severity") or {}
    if not isinstance(by_service, dict):
        by_service = {}
    if not isinstance(by_severity, dict):
        by_severity = {}

    return DashboardStatsResponse(
        total_all=int(raw["total_all"]),
        total_last_7_days=int(raw["total_last_7_days"]),
        total_last_30_days=int(raw["total_last_30_days"]),
        open_count=int(raw["open_count"]),
        in_progress_count=int(raw["in_progress_count"]),
        resolved_count=int(raw["resolved_count"]),
        closed_count=int(raw["closed_count"]),
        unassigned_count=int(raw["unassigned_count"]),
        no_jira_count=int(raw["no_jira_count"]),
        failed_count=int(raw["failed_count"]),
        by_service={str(k): int(v) for k, v in by_service.items()},
        by_severity={str(k): int(v) for k, v in by_severity.items()},
    )
