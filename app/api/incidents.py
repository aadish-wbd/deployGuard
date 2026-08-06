"""GET /api/v1/incidents, GET /api/v1/incidents/{id} — dashboard read API."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_s3_store
from app.models.incident import IncidentRecord
from app.models.schemas import IncidentListResponse
from app.services.s3_store import S3IncidentStore

router = APIRouter(prefix="/api/v1/incidents")


@router.get("", response_model=IncidentListResponse)
def list_incidents(
    service: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    page_token: Optional[str] = Query(default=None),
    s3_store: S3IncidentStore = Depends(get_s3_store),
) -> IncidentListResponse:
    return s3_store.list(service=service, status=status, limit=limit, page_token=page_token)


@router.get("/{investigation_id}", response_model=IncidentRecord)
def get_incident(
    investigation_id: str,
    s3_store: S3IncidentStore = Depends(get_s3_store),
) -> IncidentRecord:
    record = s3_store.get(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Incident {investigation_id} not found")
    return record
