"""JIRA ticket creation (FR-4).

Failures here must never block the /investigate response (NFR-7) — callers
catch JiraError and set actions.jira_created=false with the error logged.
"""
from __future__ import annotations

import httpx

from app.config import Settings
from app.core.logging_config import get_logger
from app.models.schemas import BedrockRcaOutput, InvestigateRequest

logger = get_logger(__name__)


class JiraError(Exception):
    pass


_SEVERITY_TO_PRIORITY = {
    "critical": "Highest",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}


def _derive_priority(request: InvestigateRequest, confidence: float) -> str:
    severity = request.context.severity if request.context else None
    if severity:
        return _SEVERITY_TO_PRIORITY.get(severity, "Medium")
    if confidence >= 0.85:
        return "High"
    if confidence >= 0.5:
        return "Medium"
    return "Low"


def _build_description(rca: BedrockRcaOutput) -> str:
    evidence_lines = "\n".join(f"- {item}" for item in rca.evidence) or "- (none provided)"
    return (
        f"*Root cause:* {rca.root_cause}\n\n"
        f"*Confidence:* {rca.confidence:.2f}\n\n"
        f"*RCA summary:*\n{rca.rca_summary}\n\n"
        f"*Evidence:*\n{evidence_lines}\n\n"
        f"*Suggested fix:* {rca.suggested_fix or '(none)'}\n\n"
        f"_Filed automatically by DeployGuard._"
    )


class JiraClient:
    def __init__(self, settings: Settings):
        self._settings = settings

    def create_ticket(self, request: InvestigateRequest, rca: BedrockRcaOutput) -> tuple[str, str]:
        settings = self._settings
        summary = f"[{request.service}] {rca.root_cause}"[:255]
        payload = {
            "fields": {
                "project": {"key": settings.jira_project_key},
                "summary": summary,
                "description": _build_description(rca),
                "issuetype": {"name": "Bug"},
                "priority": {"name": _derive_priority(request, rca.confidence)},
                "labels": ["deployguard", request.service],
            }
        }
        if settings.jira_default_assignee:
            payload["fields"]["assignee"] = {"accountId": settings.jira_default_assignee}

        try:
            response = httpx.post(
                f"{settings.jira_base_url}/rest/api/3/issue",
                json=payload,
                auth=(settings.jira_email, settings.jira_api_token),
                timeout=10.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise JiraError(f"JIRA ticket creation failed: {exc}") from exc

        ticket_key = response.json()["key"]
        ticket_url = f"{settings.jira_base_url}/browse/{ticket_key}"

        if settings.jira_default_watchers:
            self._add_watchers(ticket_key, settings.jira_default_watchers)

        return ticket_key, ticket_url

    def _add_watchers(self, ticket_key: str, watchers: list[str]) -> None:
        settings = self._settings
        for account_id in watchers:
            try:
                response = httpx.post(
                    f"{settings.jira_base_url}/rest/api/3/issue/{ticket_key}/watchers",
                    json=account_id,
                    auth=(settings.jira_email, settings.jira_api_token),
                    timeout=10.0,
                )
                response.raise_for_status()
            except httpx.HTTPError:
                logger.exception("jira_add_watcher_failed", extra={"ticket_key": ticket_key, "account_id": account_id})

    def create_ticket_raw(
        self, summary: str, description: str, priority: str = "Medium", labels: list[str] | None = None
    ) -> tuple[str, str]:
        """Create a JIRA ticket from raw parameters (used by AgentCore tool executor)."""
        settings = self._settings
        payload = {
            "fields": {
                "project": {"key": settings.jira_project_key},
                "summary": summary[:255],
                "description": description,
                "issuetype": {"name": "Bug"},
                "priority": {"name": priority},
                "labels": labels or ["deployguard"],
            }
        }
        if settings.jira_default_assignee:
            payload["fields"]["assignee"] = {"accountId": settings.jira_default_assignee}

        try:
            response = httpx.post(
                f"{settings.jira_base_url}/rest/api/3/issue",
                json=payload,
                auth=(settings.jira_email, settings.jira_api_token),
                timeout=10.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise JiraError(f"JIRA ticket creation failed: {exc}") from exc

        ticket_key = response.json()["key"]
        ticket_url = f"{settings.jira_base_url}/browse/{ticket_key}"
        return ticket_key, ticket_url
