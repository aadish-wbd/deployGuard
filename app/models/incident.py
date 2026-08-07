"""Canonical incident record — persisted to S3 and returned by the incidents API.

Mirrors the schema sketched in TEAM.md under Kiran's deliverables: input
payload, Bedrock output, actions taken, and operational metadata.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.models.schemas import ActionsTaken, InvestigateRequest, TriggeredBy, WorkflowStatus


class IncidentMetadata(BaseModel):
    latency_ms: int
    token_estimate: int
    triggered_by: TriggeredBy
    status: Literal["completed", "failed"]


class IncidentRecord(BaseModel):
    investigation_id: str
    timestamp: datetime
    service: str
    environment: str

    input: InvestigateRequest

    root_cause: Optional[str] = None
    confidence: Optional[float] = None
    evidence: list[str] = Field(default_factory=list)
    rca_summary: Optional[str] = None
    suggested_fix: Optional[str] = None
    error_detail: Optional[str] = None

    actions: ActionsTaken = Field(default_factory=ActionsTaken)
    metadata: IncidentMetadata
    workflow_status: WorkflowStatus = "open"

    def s3_prefix(self) -> str:
        return f"{self.timestamp.year:04d}/{self.timestamp.month:02d}/{self.investigation_id}"
