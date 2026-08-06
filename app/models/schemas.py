"""Request/response contracts for DeployGuard (FR-1, FR-2, NFR-1, NFR-4).

Field-level max_length constraints enforce the per-field payload limits from
REQUIREMENTS.md; total request body size is checked separately in
app.api.investigate (Pydantic can't see raw body bytes before parsing).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.core.limits import (
    MAX_ERROR_MESSAGE_CHARS,
    MAX_LOG_SNIPPET_CHARS,
    MAX_STACK_TRACE_CHARS,
)

TriggeredBy = Literal["databricks", "ec2", "manual"]
Severity = Literal["low", "medium", "high", "critical"]


class InvestigateContext(BaseModel):
    """Optional structured context — see NFR-1 for token-efficiency rules."""

    deploy_sha: Optional[str] = Field(default=None, max_length=64)
    log_snippet: Optional[str] = Field(default=None, max_length=MAX_LOG_SNIPPET_CHARS)
    metrics: Optional[Dict[str, str]] = None
    job_id: Optional[str] = None
    run_id: Optional[str] = None
    task_name: Optional[str] = None
    severity: Optional[Severity] = None


class InvestigateRequest(BaseModel):
    error_message: str = Field(..., max_length=MAX_ERROR_MESSAGE_CHARS, min_length=1)
    stack_trace: Optional[str] = Field(default=None, max_length=MAX_STACK_TRACE_CHARS)
    service: str = Field(..., min_length=1, max_length=128)
    environment: str = Field(..., min_length=1, max_length=32)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    context: Optional[InvestigateContext] = None
    triggered_by: TriggeredBy = "manual"


class BedrockRcaOutput(BaseModel):
    """Structured JSON schema DeployGuard requires from the Bedrock agent (NFR-4)."""

    root_cause: str = Field(..., max_length=200)
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list, max_length=5)
    rca_summary: str = Field(..., max_length=500)
    suggested_fix: str = Field(default="", max_length=300)


class ActionsTaken(BaseModel):
    jira_ticket: Optional[str] = None
    jira_url: Optional[str] = None
    jira_created: bool = False
    slack_sent: bool = False


class InvestigateResponse(BaseModel):
    investigation_id: str
    status: Literal["completed", "failed"]
    root_cause: Optional[str] = None
    confidence: Optional[float] = None
    rca_summary: Optional[str] = None
    evidence: List[str] = Field(default_factory=list)
    suggested_fix: Optional[str] = None
    s3_report_url: Optional[str] = None
    actions: ActionsTaken = Field(default_factory=ActionsTaken)
    error_detail: Optional[str] = None
    cached: bool = False


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    bedrock_reachable: bool
    detail: Optional[str] = None


class IncidentSummary(BaseModel):
    investigation_id: str
    timestamp: datetime
    service: str
    environment: str
    status: Literal["completed", "failed"]
    root_cause: Optional[str] = None
    confidence: Optional[float] = None
    jira_ticket: Optional[str] = None


class IncidentListResponse(BaseModel):
    items: List[IncidentSummary]
    next_page_token: Optional[str] = None
