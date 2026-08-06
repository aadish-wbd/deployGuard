"""S3 incident persistence and listing.

Layout (per TEAM.md):

    s3://{bucket}/{year}/{month}/{investigation_id}/
        incident.json   # full metadata (IncidentRecord)
        rca.md           # human-readable RCA report
        input.json        # original request payload

A flat copy of incident.json also lands at `by_id/{investigation_id}.json`
so GET /api/v1/incidents/{id} is a single lookup instead of a bucket scan,
and a one-line-per-incident index at `index/incidents.jsonl` backs
GET /api/v1/incidents list/filter without scanning every object.
"""
from __future__ import annotations

import json
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from app.config import Settings
from app.core.logging_config import get_logger
from app.models.incident import IncidentRecord
from app.models.schemas import IncidentListResponse, IncidentSummary

logger = get_logger(__name__)


def _build_rca_markdown(record: IncidentRecord) -> str:
    evidence_lines = "\n".join(f"- {item}" for item in record.evidence) or "- (none)"
    return (
        f"# RCA — {record.investigation_id}\n\n"
        f"- **Service:** {record.service}\n"
        f"- **Environment:** {record.environment}\n"
        f"- **Status:** {record.metadata.status}\n"
        f"- **Timestamp:** {record.timestamp.isoformat()}\n\n"
        f"## Root cause\n{record.root_cause or '(unavailable)'}\n\n"
        f"## Confidence\n{record.confidence if record.confidence is not None else 'N/A'}\n\n"
        f"## Summary\n{record.rca_summary or '(unavailable)'}\n\n"
        f"## Evidence\n{evidence_lines}\n\n"
        f"## Suggested fix\n{record.suggested_fix or '(none)'}\n"
    )


class S3IncidentStore:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = boto3.client("s3", region_name=settings.aws_region)

    def save(self, record: IncidentRecord) -> str:
        bucket = self._settings.s3_bucket
        prefix = record.s3_prefix()

        incident_json = record.model_dump_json(indent=2)
        input_json = record.input.model_dump_json(indent=2)
        rca_md = _build_rca_markdown(record)

        self._client.put_object(Bucket=bucket, Key=f"{prefix}/incident.json", Body=incident_json.encode("utf-8"))
        self._client.put_object(Bucket=bucket, Key=f"{prefix}/rca.md", Body=rca_md.encode("utf-8"))
        self._client.put_object(Bucket=bucket, Key=f"{prefix}/input.json", Body=input_json.encode("utf-8"))
        self._client.put_object(
            Bucket=bucket, Key=f"by_id/{record.investigation_id}.json", Body=incident_json.encode("utf-8")
        )
        self._append_to_index(record)

        return f"s3://{bucket}/{prefix}/"

    def _append_to_index(self, record: IncidentRecord) -> None:
        summary = IncidentSummary(
            investigation_id=record.investigation_id,
            timestamp=record.timestamp,
            service=record.service,
            environment=record.environment,
            status=record.metadata.status,
            root_cause=record.root_cause,
            confidence=record.confidence,
            jira_ticket=record.actions.jira_ticket,
        )
        bucket = self._settings.s3_bucket
        key = self._settings.s3_index_key
        try:
            existing = self._client.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
        except ClientError:
            existing = ""
        updated = existing + summary.model_dump_json() + "\n"
        self._client.put_object(Bucket=bucket, Key=key, Body=updated.encode("utf-8"))

    def get(self, investigation_id: str) -> Optional[IncidentRecord]:
        bucket = self._settings.s3_bucket
        try:
            body = self._client.get_object(Bucket=bucket, Key=f"by_id/{investigation_id}.json")["Body"].read()
        except ClientError:
            return None
        return IncidentRecord.model_validate_json(body)

    def list(
        self,
        service: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
        page_token: Optional[str] = None,
    ) -> IncidentListResponse:
        bucket = self._settings.s3_bucket
        key = self._settings.s3_index_key
        try:
            body = self._client.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
        except ClientError:
            return IncidentListResponse(items=[])

        summaries = [IncidentSummary.model_validate_json(line) for line in body.splitlines() if line.strip()]
        summaries.sort(key=lambda s: s.timestamp, reverse=True)

        if service:
            summaries = [s for s in summaries if s.service == service]
        if status:
            summaries = [s for s in summaries if s.status == status]

        offset = int(page_token) if page_token else 0
        page = summaries[offset : offset + limit]
        next_offset = offset + limit
        next_token = str(next_offset) if next_offset < len(summaries) else None

        return IncidentListResponse(items=page, next_page_token=next_token)
