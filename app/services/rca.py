"""Shared RCA markdown rendering for S3 archival."""
from __future__ import annotations

from app.models.incident import IncidentRecord


def build_rca_markdown(record: IncidentRecord) -> str:
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
