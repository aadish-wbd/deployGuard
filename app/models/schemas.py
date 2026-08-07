"""Request/response contracts for DeployGuard (FR-1, FR-2, NFR-1, NFR-4).

Field-level max_length constraints enforce the per-field payload limits from
REQUIREMENTS.md; total request body size is checked separately in
app.api.investigate (Pydantic can't see raw body bytes before parsing).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.limits import (
    MAX_ERROR_MESSAGE_CHARS,
    MAX_LOG_SNIPPET_CHARS,
    MAX_NOTEBOOK_CONTEXT_CHARS,
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
    notebook_context: Optional[str] = Field(default=None, max_length=MAX_NOTEBOOK_CONTEXT_CHARS)


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

    @model_validator(mode="before")
    @classmethod
    def _truncate_overlong_strings(cls, data: object) -> object:
        """Bedrock sometimes exceeds char limits — trim instead of failing the investigation."""
        if not isinstance(data, dict):
            return data
        limits = {"root_cause": 200, "rca_summary": 500, "suggested_fix": 300}
        for key, max_len in limits.items():
            value = data.get(key)
            if isinstance(value, str) and len(value) > max_len:
                data[key] = value[: max_len - 3] + "..."
        evidence = data.get("evidence")
        if isinstance(evidence, list):
            data["evidence"] = [item[:497] + "..." if isinstance(item, str) and len(item) > 500 else item for item in evidence[:5]]
        return data


class ActionsTaken(BaseModel):
    jira_ticket: Optional[str] = None
    jira_url: Optional[str] = None
    jira_created: bool = False
    jira_reused: bool = False
    slack_sent: bool = False


class ExistingInvestigation(BaseModel):
    """Prior completed investigation for the same error fingerprint."""

    jira_ticket: str
    jira_url: str
    investigation_id: Optional[str] = None
    root_cause: Optional[str] = None
    confidence: Optional[float] = None
    rca_summary: Optional[str] = None
    suggested_fix: Optional[str] = None
    evidence: List[str] = Field(default_factory=list)
    s3_report_url: Optional[str] = None


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
    existing_ticket: bool = False


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    bedrock_reachable: bool
    postgres_reachable: Optional[bool] = None
    detail: Optional[str] = None


WorkflowStatus = Literal["open", "in_progress", "resolved", "closed"]


class IncidentSummary(BaseModel):
    investigation_id: str
    timestamp: datetime
    service: str
    environment: str
    status: Literal["completed", "failed"]
    root_cause: Optional[str] = None
    confidence: Optional[float] = None
    jira_ticket: Optional[str] = None
    jira_url: Optional[str] = None
    rca_summary: Optional[str] = None
    severity: Optional[Severity] = None
    workflow_status: WorkflowStatus = "open"
    triggered_by: Optional[TriggeredBy] = None
    slack_sent: bool = False


class DashboardStatsResponse(BaseModel):
    total_all: int
    total_last_7_days: int
    total_last_30_days: int
    open_count: int
    in_progress_count: int
    resolved_count: int
    closed_count: int
    unassigned_count: int
    no_jira_count: int
    failed_count: int
    by_service: Dict[str, int] = Field(default_factory=dict)
    by_severity: Dict[str, int] = Field(default_factory=dict)


class IncidentListResponse(BaseModel):
    items: List[IncidentSummary]
    next_page_token: Optional[str] = None


class DatabricksRunContextRequest(BaseModel):
    """Fetch failure context from a Databricks job run (step 1 of 2)."""

    run_id: str = Field(..., min_length=1, max_length=64)
    job_id: Optional[str] = Field(default=None, max_length=64)


class DatabricksInvestigateRequest(BaseModel):
    """Automated Databricks flow: fetch run context then invoke DeployGuard."""

    run_id: str = Field(..., min_length=1, max_length=64)
    service: str = Field(default="Databricks", min_length=1, max_length=128)
    environment: str = Field(..., min_length=1, max_length=32)
    job_id: Optional[str] = Field(default=None, max_length=64)
    task_name: Optional[str] = Field(default=None, max_length=128)
    severity: Optional[Severity] = None


class DatabricksRunContextResponse(BaseModel):
    """Failure details extracted from a Databricks run export.

    Pass to POST /api/v1/investigate via to_investigate_request() or map fields manually.
    """

    run_id: str
    job_id: Optional[str] = None
    error_message: str
    stack_trace: Optional[str] = None
    log_snippet: Optional[str] = None
    task_name: Optional[str] = None
    notebook_name: Optional[str] = None
    notebook_context: Optional[str] = None

    def to_investigate_request(
        self,
        *,
        service: str,
        environment: str,
        severity: Optional[Severity] = None,
    ) -> InvestigateRequest:
        return InvestigateRequest(
            error_message=self.error_message,
            stack_trace=self.stack_trace,
            service=service,
            environment=environment,
            context=InvestigateContext(
                job_id=self.job_id,
                run_id=self.run_id,
                task_name=self.task_name,
                log_snippet=self.log_snippet,
                severity=severity,
                notebook_context=self.notebook_context,
            ),
            triggered_by="databricks",
        )


class DatabricksWebhookRun(BaseModel):
    run_id: str
    parent_run_id: Optional[str] = None

    @field_validator("run_id", "parent_run_id", mode="before")
    @classmethod
    def _coerce_run_id(cls, value: object) -> object:
        if value is None:
            return value
        return str(value)


class DatabricksWebhookJob(BaseModel):
    job_id: str
    name: str = "unknown"

    @field_validator("job_id", mode="before")
    @classmethod
    def _coerce_job_id(cls, value: object) -> str:
        return str(value)


class DatabricksWebhookTask(BaseModel):
    task_key: str


class DatabricksWebhookPayload(BaseModel):
    """Native Databricks job notification webhook body (jobs.on_failure, etc.)."""

    event_type: str
    workspace_id: Optional[str] = None
    run: DatabricksWebhookRun
    job: DatabricksWebhookJob
    task: Optional[DatabricksWebhookTask] = None

    @field_validator("workspace_id", mode="before")
    @classmethod
    def _coerce_workspace_id(cls, value: object) -> object:
        if value is None:
            return value
        return str(value)

    def extract_run_id(self) -> str:
        """Run ID for POST /api/v1/databricks/runs/context.

        Job-level webhooks set run.run_id to the job run. Task-level webhooks set
        run.run_id to the failed task run and parent_run_id to the enclosing job run.
        Export/context must use the task run_id when task is present.
        """
        return self.run.run_id

    def to_context_request(self) -> DatabricksRunContextRequest:
        return DatabricksRunContextRequest(
            run_id=self.extract_run_id(),
            job_id=self.job.job_id,
        )


class DatabricksWebhookResponse(BaseModel):
    status: Literal["accepted", "ignored"]
    run_id: Optional[str] = None
    event_type: Optional[str] = None
    detail: Optional[str] = None
