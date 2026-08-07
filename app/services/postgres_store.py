"""PostgreSQL incident store — dashboard queries and structured persistence.

S3 remains the archive for full incident.json / rca.md / input.json.
Postgres holds denormalized rows plus S3 URIs for the dashboard UI.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator, Optional

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

from app.config import Settings
from app.core.logging_config import get_logger
from app.models.incident import IncidentMetadata, IncidentRecord
from app.models.schemas import (
    ActionsTaken,
    IncidentListResponse,
    IncidentSummary,
    InvestigateRequest,
)

logger = get_logger(__name__)

_INSERT_INCIDENT = """
INSERT INTO incidents (
    investigation_id,
    occurred_at,
    service,
    environment,
    triggered_by,
    input_payload,
    error_message,
    stack_trace,
    severity,
    deploy_sha,
    log_snippet,
    databricks_job_id,
    databricks_run_id,
    databricks_task,
    root_cause,
    confidence,
    rca_summary,
    suggested_fix,
    evidence,
    error_detail,
    rca_s3_uri,
    s3_report_uri,
    investigation_status,
    workflow_status,
    assigned_developer_id,
    jira_ticket,
    jira_url,
    jira_created,
    slack_sent,
    latency_ms,
    token_estimate
) VALUES (
    %(investigation_id)s,
    %(occurred_at)s,
    %(service)s,
    %(environment)s,
    %(triggered_by)s,
    %(input_payload)s,
    %(error_message)s,
    %(stack_trace)s,
    %(severity)s,
    %(deploy_sha)s,
    %(log_snippet)s,
    %(databricks_job_id)s,
    %(databricks_run_id)s,
    %(databricks_task)s,
    %(root_cause)s,
    %(confidence)s,
    %(rca_summary)s,
    %(suggested_fix)s,
    %(evidence)s,
    %(error_detail)s,
    %(rca_s3_uri)s,
    %(s3_report_uri)s,
    %(investigation_status)s,
    'open',
    NULL,
    %(jira_ticket)s,
    %(jira_url)s,
    %(jira_created)s,
    %(slack_sent)s,
    %(latency_ms)s,
    %(token_estimate)s
)
ON CONFLICT (investigation_id) DO NOTHING
"""


class PostgresIncidentStore:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._pool: Optional[ThreadedConnectionPool] = None
        if settings.postgres_enabled:
            self._pool = ThreadedConnectionPool(
                minconn=1,
                maxconn=5,
                host=settings.pghost,
                port=settings.pgport,
                dbname=settings.pgdatabase,
                user=settings.pguser,
                password=settings.pgpassword,
                connect_timeout=10,
            )

    def close(self) -> None:
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        if self._pool is None:
            raise RuntimeError("PostgreSQL store is not configured")
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def ping(self) -> bool:
        if self._pool is None:
            return False
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            return True
        except Exception:
            logger.exception("postgres_ping_failed")
            return False

    def save(self, record: IncidentRecord, *, rca_s3_uri: str, s3_report_uri: str) -> None:
        ctx = record.input.context
        params = {
            "investigation_id": record.investigation_id,
            "occurred_at": record.timestamp,
            "service": record.service,
            "environment": record.environment,
            "triggered_by": record.input.triggered_by,
            "input_payload": json.dumps(record.input.model_dump(mode="json")),
            "error_message": record.input.error_message,
            "stack_trace": record.input.stack_trace,
            "severity": ctx.severity if ctx else None,
            "deploy_sha": ctx.deploy_sha if ctx else None,
            "log_snippet": ctx.log_snippet if ctx else None,
            "databricks_job_id": ctx.job_id if ctx else None,
            "databricks_run_id": ctx.run_id if ctx else None,
            "databricks_task": ctx.task_name if ctx else None,
            "root_cause": record.root_cause,
            "confidence": record.confidence,
            "rca_summary": record.rca_summary,
            "suggested_fix": record.suggested_fix,
            "evidence": json.dumps(record.evidence),
            "error_detail": record.error_detail,
            "rca_s3_uri": rca_s3_uri,
            "s3_report_uri": s3_report_uri,
            "investigation_status": record.metadata.status,
            "jira_ticket": record.actions.jira_ticket,
            "jira_url": record.actions.jira_url,
            "jira_created": record.actions.jira_created,
            "slack_sent": record.actions.slack_sent,
            "latency_ms": record.metadata.latency_ms,
            "token_estimate": record.metadata.token_estimate,
        }
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_INSERT_INCIDENT, params)

    def find_existing_jira(
        self,
        *,
        error_message: str,
        service: str,
        environment: str,
    ) -> Optional["ExistingInvestigation"]:
        from app.models.schemas import ExistingInvestigation

        query = """
            SELECT
                investigation_id::text,
                jira_ticket,
                jira_url,
                root_cause,
                confidence,
                rca_summary,
                suggested_fix,
                evidence,
                s3_report_uri
            FROM incidents
            WHERE error_message = %s
              AND service = %s
              AND environment = %s
              AND jira_ticket IS NOT NULL
              AND investigation_status::text = 'completed'
            ORDER BY occurred_at DESC
            LIMIT 1
        """
        with self._connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, (error_message, service, environment))
                row = cur.fetchone()
        if row is None:
            return None

        evidence = row["evidence"]
        if isinstance(evidence, str):
            evidence = json.loads(evidence)

        return ExistingInvestigation(
            investigation_id=row["investigation_id"],
            jira_ticket=row["jira_ticket"],
            jira_url=row["jira_url"],
            root_cause=row["root_cause"],
            confidence=float(row["confidence"]) if row["confidence"] is not None else None,
            rca_summary=row["rca_summary"],
            suggested_fix=row["suggested_fix"],
            evidence=evidence or [],
            s3_report_url=row["s3_report_uri"],
        )

    def get(self, investigation_id: str) -> Optional[IncidentRecord]:
        query = """
            SELECT
                investigation_id::text,
                occurred_at,
                service,
                environment,
                input_payload,
                root_cause,
                confidence,
                evidence,
                rca_summary,
                suggested_fix,
                error_detail,
                investigation_status::text,
                triggered_by::text,
                latency_ms,
                token_estimate,
                jira_ticket,
                jira_url,
                jira_created,
                slack_sent,
                workflow_status::text
            FROM incidents
            WHERE investigation_id = %s
        """
        with self._connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, (investigation_id,))
                row = cur.fetchone()
        if row is None:
            return None
        return _row_to_incident_record(row)

    def update_workflow_status(self, investigation_id: str, workflow_status: str) -> Optional[IncidentRecord]:
        query = """
            UPDATE incidents
            SET workflow_status = %s
            WHERE investigation_id = %s
            RETURNING
                investigation_id::text,
                occurred_at,
                service,
                environment,
                input_payload,
                root_cause,
                confidence,
                evidence,
                rca_summary,
                suggested_fix,
                error_detail,
                investigation_status::text,
                triggered_by::text,
                latency_ms,
                token_estimate,
                jira_ticket,
                jira_url,
                jira_created,
                slack_sent,
                workflow_status::text
        """
        with self._connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, (workflow_status, investigation_id))
                row = cur.fetchone()
        if row is None:
            return None
        return _row_to_incident_record(row)

    def list(
        self,
        service: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
        page_token: Optional[str] = None,
    ) -> IncidentListResponse:
        filters = ["1=1"]
        params: list[Any] = []
        if service:
            filters.append("service = %s")
            params.append(service)
        if status:
            filters.append("investigation_status::text = %s")
            params.append(status)

        offset = int(page_token) if page_token else 0
        params.extend([limit + 1, offset])

        query = f"""
            SELECT
                investigation_id::text,
                occurred_at,
                service,
                environment,
                investigation_status::text AS status,
                root_cause,
                confidence,
                jira_ticket,
                jira_url,
                rca_summary,
                severity::text AS severity,
                workflow_status::text AS workflow_status,
                triggered_by::text AS triggered_by,
                slack_sent
            FROM incidents
            WHERE {' AND '.join(filters)}
            ORDER BY occurred_at DESC
            LIMIT %s OFFSET %s
        """
        with self._connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        has_more = len(rows) > limit
        page_rows = rows[:limit]
        items = [
            IncidentSummary(
                investigation_id=row["investigation_id"],
                timestamp=row["occurred_at"],
                service=row["service"],
                environment=row["environment"],
                status=row["status"],
                root_cause=row["root_cause"],
                confidence=float(row["confidence"]) if row["confidence"] is not None else None,
                jira_ticket=row["jira_ticket"],
                jira_url=row["jira_url"],
                rca_summary=row["rca_summary"],
                severity=row["severity"],
                workflow_status=row["workflow_status"] or "open",
                triggered_by=row["triggered_by"],
                slack_sent=bool(row["slack_sent"]),
            )
            for row in page_rows
        ]
        next_token = str(offset + limit) if has_more else None
        return IncidentListResponse(items=items, next_page_token=next_token)

    def dashboard_stats(self, service: Optional[str] = None) -> dict[str, Any]:
        with self._connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM fn_dashboard_stats(%s)", (service,))
                row = cur.fetchone()
        if row is None:
            raise RuntimeError("fn_dashboard_stats returned no rows")
        return dict(row)


def _row_to_incident_record(row: dict[str, Any]) -> IncidentRecord:
    input_data = row["input_payload"]
    if isinstance(input_data, str):
        input_data = json.loads(input_data)
    evidence = row["evidence"]
    if isinstance(evidence, str):
        evidence = json.loads(evidence)

    request = InvestigateRequest.model_validate(input_data)
    if row.get("triggered_by"):
        request = request.model_copy(update={"triggered_by": row["triggered_by"]})

    return IncidentRecord(
        investigation_id=row["investigation_id"],
        timestamp=row["occurred_at"],
        service=row["service"],
        environment=row["environment"],
        input=request,
        root_cause=row["root_cause"],
        confidence=float(row["confidence"]) if row["confidence"] is not None else None,
        evidence=evidence or [],
        rca_summary=row["rca_summary"],
        suggested_fix=row["suggested_fix"],
        error_detail=row["error_detail"],
        actions=ActionsTaken(
            jira_ticket=row["jira_ticket"],
            jira_url=row["jira_url"],
            jira_created=bool(row["jira_created"]),
            slack_sent=bool(row["slack_sent"]),
        ),
        metadata=IncidentMetadata(
            latency_ms=row["latency_ms"],
            token_estimate=row["token_estimate"],
            triggered_by=row["triggered_by"],
            status=row["investigation_status"],
        ),
        workflow_status=row.get("workflow_status") or "open",
    )


def s3_uris_for_record(settings: Settings, record: IncidentRecord) -> tuple[str, str]:
    prefix = record.s3_prefix()
    bucket = settings.s3_bucket
    report_uri = f"s3://{bucket}/{prefix}/"
    rca_uri = f"s3://{bucket}/{prefix}/rca.md"
    return report_uri, rca_uri
