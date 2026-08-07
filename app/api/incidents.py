"""GET /api/v1/incidents, GET /api/v1/incidents/{id} — dashboard read API."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.config import Settings
from app.dependencies import get_postgres_store, get_s3_store, get_settings_dep
from app.models.incident import IncidentRecord
from app.models.schemas import IncidentListResponse, UpdateWorkflowStatusRequest
from app.services.postgres_store import PostgresIncidentStore
from app.services.rca import build_rca_markdown
from app.services.s3_store import S3IncidentStore

router = APIRouter(prefix="/api/v1/incidents")


def _list_incidents(
    postgres_store: Optional[PostgresIncidentStore],
    s3_store: S3IncidentStore,
    service: Optional[str],
    status: Optional[str],
    limit: int,
    page_token: Optional[str],
) -> IncidentListResponse:
    if postgres_store is not None:
        try:
            return postgres_store.list(service=service, status=status, limit=limit, page_token=page_token)
        except Exception:
            pass
    return s3_store.list(service=service, status=status, limit=limit, page_token=page_token)


def _get_incident(
    investigation_id: str,
    postgres_store: Optional[PostgresIncidentStore],
    s3_store: S3IncidentStore,
) -> Optional[IncidentRecord]:
    if postgres_store is not None:
        try:
            record = postgres_store.get(investigation_id)
            if record is not None:
                return record
        except Exception:
            pass
    return s3_store.get(investigation_id)


@router.get("", response_model=IncidentListResponse)
def list_incidents(
    service: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    page_token: Optional[str] = Query(default=None),
    settings: Settings = Depends(get_settings_dep),
    postgres_store: Optional[PostgresIncidentStore] = Depends(get_postgres_store),
    s3_store: S3IncidentStore = Depends(get_s3_store),
) -> IncidentListResponse:
    return _list_incidents(postgres_store, s3_store, service, status, limit, page_token)


@router.get("/{investigation_id}", response_model=IncidentRecord)
def get_incident(
    investigation_id: str,
    settings: Settings = Depends(get_settings_dep),
    postgres_store: Optional[PostgresIncidentStore] = Depends(get_postgres_store),
    s3_store: S3IncidentStore = Depends(get_s3_store),
) -> IncidentRecord:
    record = _get_incident(investigation_id, postgres_store, s3_store)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Incident {investigation_id} not found")
    return record


@router.patch("/{investigation_id}/workflow-status", response_model=IncidentRecord)
def update_workflow_status(
    investigation_id: str,
    body: UpdateWorkflowStatusRequest,
    postgres_store: Optional[PostgresIncidentStore] = Depends(get_postgres_store),
) -> IncidentRecord:
    if postgres_store is None:
        raise HTTPException(status_code=503, detail="Workflow status updates require PostgreSQL")
    try:
        record = postgres_store.update_workflow_status(investigation_id, body.workflow_status)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to update workflow status") from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"Incident {investigation_id} not found")
    return record


@router.get("/{investigation_id}/rca")
def download_rca_report(
    investigation_id: str,
    postgres_store: Optional[PostgresIncidentStore] = Depends(get_postgres_store),
    s3_store: S3IncidentStore = Depends(get_s3_store),
) -> Response:
    record = _get_incident(investigation_id, postgres_store, s3_store)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Incident {investigation_id} not found")
    if record.metadata.status != "completed":
        raise HTTPException(status_code=400, detail="RCA report is only available for completed investigations")
    markdown = build_rca_markdown(record)
    return Response(
        content=markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="rca-{investigation_id}.md"'},
    )
