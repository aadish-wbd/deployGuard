"""JIRA ticket creation (FR-4).

Failures here must never block the /investigate response (NFR-7) — callers
catch JiraError and set actions.jira_created=false with the error logged.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from app.config import Settings
from app.core.investigation_fingerprint import investigation_fingerprint_label
from app.core.logging_config import get_logger
from app.models.schemas import BedrockRcaOutput, ExistingInvestigation, InvestigateRequest

logger = get_logger(__name__)


class JiraError(Exception):
    pass


_SEVERITY_TO_PRIORITY = {
    "critical": "Highest",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}

_COMMON_ISSUE_TYPES = ("Bug", "Task", "Story", "Incident", "Sub-task")

_BUG_SIGNALS = (
    "exception",
    "error",
    "nullpointer",
    "null pointer",
    "bug",
    "regression",
    "crash",
    "stack trace",
    "500 internal",
    "503 service",
    "timeout",
    "failed to",
    "cannot ",
    "broken",
    "defect",
)

_INCIDENT_SIGNALS = (
    "outage",
    "sev-",
    "sev ",
    "production down",
    "major incident",
    "service unavailable",
)

_STORY_SIGNALS = (
    "missing feature",
    "feature gap",
    "not implemented",
    "enhancement",
)


def _normalize_issue_type(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        return ""
    for allowed in _COMMON_ISSUE_TYPES:
        if cleaned.lower() == allowed.lower():
            return allowed
    return cleaned


def _derive_issue_type(rca: BedrockRcaOutput, settings: Settings) -> str:
    """Pick a JIRA issue type from agent output, with heuristic fallback."""
    if rca.issue_type:
        normalized = _normalize_issue_type(rca.issue_type)
        if normalized:
            return normalized

    text = " ".join(
        [
            rca.root_cause,
            rca.rca_summary,
            rca.suggested_fix,
            " ".join(rca.evidence),
        ]
    ).lower()
    if any(signal in text for signal in _INCIDENT_SIGNALS):
        return "Incident"
    if any(signal in text for signal in _BUG_SIGNALS):
        return "Bug"
    if any(signal in text for signal in _STORY_SIGNALS):
        return "Story"
    return settings.jira_issue_type


def _derive_priority(request: InvestigateRequest, confidence: float) -> str:
    severity = request.context.severity if request.context else None
    if severity:
        return _SEVERITY_TO_PRIORITY.get(severity, "Medium")
    if confidence >= 0.85:
        return "High"
    if confidence >= 0.5:
        return "Medium"
    return "Low"


def _jira_api_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _is_scoped_api_token(token: str) -> bool:
    """Scoped Atlassian tokens (ATCTT...) must use the api.atlassian.com gateway."""
    return token.startswith("ATCTT")


def fetch_cloud_id(site_url: str) -> str:
    """Resolve a Jira Cloud site URL to its cloud ID (public tenant_info endpoint)."""
    response = httpx.get(_jira_api_url(site_url, "/_edge/tenant_info"), timeout=10.0)
    response.raise_for_status()
    cloud_id = response.json().get("cloudId")
    if not cloud_id:
        raise ValueError(f"cloudId missing from tenant_info for {site_url}")
    return cloud_id


def resolve_jira_rest_base(settings: Settings) -> str:
    """Base URL for Jira REST API calls (site URL or scoped-token gateway)."""
    if settings.jira_cloud_id:
        return f"https://api.atlassian.com/ex/jira/{settings.jira_cloud_id}"

    if _is_scoped_api_token(settings.jira_api_token) and settings.jira_base_url:
        cloud_id = fetch_cloud_id(settings.jira_base_url)
        logger.info("jira_using_scoped_token_gateway", extra={"cloud_id": cloud_id})
        return f"https://api.atlassian.com/ex/jira/{cloud_id}"

    return settings.jira_base_url.rstrip("/")


def _jira_browse_url(settings: Settings, ticket_key: str) -> str:
    return _jira_api_url(settings.jira_base_url, f"/browse/{ticket_key}")


def _format_jira_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except json.JSONDecodeError:
        return response.text[:500] or response.reason_phrase

    parts: list[str] = []
    if body.get("errorMessages"):
        parts.extend(str(item) for item in body["errorMessages"])
    if body.get("errors"):
        parts.extend(f"{key}: {value}" for key, value in body["errors"].items())
    return "; ".join(parts) or response.text[:500] or response.reason_phrase


def validate_jira_config(settings: Settings) -> None:
    """Log JIRA project/issue-type availability at startup (non-fatal)."""
    if not settings.enable_jira or not settings.jira_base_url:
        return
    if not settings.jira_email or not settings.jira_api_token:
        logger.warning("jira_config_incomplete", extra={"detail": "JIRA_EMAIL or JIRA_API_TOKEN not set"})
        return

    auth = (settings.jira_email, settings.jira_api_token)
    rest_base = resolve_jira_rest_base(settings)

    try:
        project_resp = httpx.get(
            _jira_api_url(rest_base, f"/rest/api/3/project/{settings.jira_project_key}"),
            auth=auth,
            timeout=10.0,
        )
        if project_resp.status_code == 404:
            search_resp = httpx.get(
                _jira_api_url(rest_base, "/rest/api/3/project/search?maxResults=20"),
                auth=auth,
                timeout=10.0,
            )
            available = []
            if search_resp.status_code == 200:
                available = [item.get("key") for item in search_resp.json().get("values", []) if item.get("key")]
            logger.warning(
                "jira_project_not_found",
                extra={"project_key": settings.jira_project_key, "available_projects": available},
            )
            print(
                f"\nWARNING: JIRA project {settings.jira_project_key!r} not found on {settings.jira_base_url.rstrip('/')}. "
                f"Available projects: {available or '(none visible)'}\n"
            )
            return

        if project_resp.status_code == 401:
            print(
                "\nWARNING: JIRA auth failed (401). Scoped tokens (ATCTT...) require either "
                "JIRA_CLOUD_ID or a classic token (ATATT...). "
                "Cloud ID: curl https://YOUR-SITE.atlassian.net/_edge/tenant_info\n"
            )
            return

        project_resp.raise_for_status()

        meta_resp = httpx.get(
            _jira_api_url(
                rest_base,
                f"/rest/api/3/issue/createmeta/{settings.jira_project_key}/issuetypes",
            ),
            auth=auth,
            timeout=10.0,
        )
        if meta_resp.status_code == 200:
            issue_types = [item.get("name") for item in meta_resp.json().get("issueTypes", []) if item.get("name")]
            if settings.jira_issue_type not in issue_types:
                logger.warning(
                    "jira_issue_type_invalid",
                    extra={
                        "issue_type": settings.jira_issue_type,
                        "available_issue_types": issue_types,
                    },
                )
                print(
                    f"\nWARNING: JIRA issue type {settings.jira_issue_type!r} not valid for project "
                    f"{settings.jira_project_key!r}. Available: {issue_types or '(none)'}\n"
                )
    except httpx.HTTPError as exc:
        logger.warning("jira_config_validation_failed", extra={"error": str(exc)})


def _text_node(text: str, *, strong: bool = False, em: bool = False) -> dict:
    node: dict = {"type": "text", "text": text}
    marks = []
    if strong:
        marks.append({"type": "strong"})
    if em:
        marks.append({"type": "em"})
    if marks:
        node["marks"] = marks
    return node


def _paragraph(*content: dict) -> dict:
    return {"type": "paragraph", "content": list(content)}


def _heading(text: str, level: int = 3) -> dict:
    return {"type": "heading", "attrs": {"level": level}, "content": [_text_node(text)]}


def _bullet_list(items: list[str]) -> dict:
    return {
        "type": "bulletList",
        "content": [{"type": "listItem", "content": [_paragraph(_text_node(item))]} for item in items],
    }


def plain_text_to_adf(text: str) -> dict:
    """Convert plain text to JIRA Cloud v3 Atlassian Document Format."""
    content = []
    for block in text.split("\n\n"):
        stripped = block.strip()
        if not stripped:
            continue
        lines = stripped.splitlines()
        if all(line.startswith("- ") for line in lines):
            content.append(_bullet_list([line[2:] for line in lines]))
        else:
            content.append(_paragraph(_text_node(stripped.replace("\n", " "))))
    if not content:
        content.append(_paragraph(_text_node(text or "(empty)")))
    return {"type": "doc", "version": 1, "content": content}


def _build_description(rca: BedrockRcaOutput) -> dict:
    content = [
        _paragraph(_text_node("Root cause: ", strong=True), _text_node(rca.root_cause)),
        _paragraph(_text_node("Confidence: ", strong=True), _text_node(f"{rca.confidence:.2f}")),
        _heading("RCA summary"),
        _paragraph(_text_node(rca.rca_summary)),
        _heading("Evidence"),
    ]
    if rca.evidence:
        content.append(_bullet_list(rca.evidence))
    else:
        content.append(_paragraph(_text_node("(none provided)")))
    content.extend(
        [
            _paragraph(
                _text_node("Suggested fix: ", strong=True),
                _text_node(rca.suggested_fix or "(none)"),
            ),
            _paragraph(_text_node("Filed automatically by DeployGuard.", em=True)),
        ]
    )
    return {"type": "doc", "version": 1, "content": content}


def _issue_labels(request: InvestigateRequest) -> list[str]:
    return [
        "deployguard",
        request.service,
        investigation_fingerprint_label(request.error_message, request.service, request.environment),
    ]


class JiraClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._rest_base = resolve_jira_rest_base(settings)

    def _auth(self) -> tuple[str, str]:
        settings = self._settings
        return settings.jira_email, settings.jira_api_token

    def _build_fields(
        self,
        *,
        summary: str,
        description: dict,
        priority: Optional[str],
        labels: list[str],
        issue_type: Optional[str] = None,
    ) -> dict[str, Any]:
        settings = self._settings
        fields: dict[str, Any] = {
            "project": {"key": settings.jira_project_key},
            "summary": summary[:255],
            "description": description,
            "issuetype": {"name": issue_type or settings.jira_issue_type},
            "labels": labels,
        }
        if priority and settings.jira_set_priority:
            fields["priority"] = {"name": priority}
        if settings.jira_default_assignee:
            fields["assignee"] = {"accountId": settings.jira_default_assignee}
        return fields

    def _submit_issue(self, fields: dict[str, Any]) -> tuple[str, str]:
        settings = self._settings
        response = httpx.post(
            _jira_api_url(self._rest_base, "/rest/api/3/issue"),
            json={"fields": fields},
            auth=self._auth(),
            timeout=10.0,
        )
        if response.is_success:
            ticket_key = response.json()["key"]
            ticket_url = _jira_browse_url(settings, ticket_key)
            return ticket_key, ticket_url

        detail = _format_jira_error(response)
        raise JiraError(
            f"JIRA ticket creation failed ({response.status_code}): {detail} "
            f"(project={settings.jira_project_key}, issuetype={fields.get('issuetype', {}).get('name')})"
        )

    def _create_issue_with_fallbacks(
        self,
        *,
        summary: str,
        description: dict,
        priority: Optional[str],
        labels: list[str],
        issue_type: Optional[str] = None,
    ) -> tuple[str, str]:
        settings = self._settings
        primary_type = issue_type or settings.jira_issue_type
        attempts: list[dict[str, Any]] = [
            self._build_fields(
                summary=summary,
                description=description,
                priority=priority,
                labels=labels,
                issue_type=primary_type,
            ),
        ]

        if settings.jira_set_priority and priority:
            no_priority = self._build_fields(
                summary=summary,
                description=description,
                priority=None,
                labels=labels,
                issue_type=primary_type,
            )
            if no_priority not in attempts:
                attempts.append(no_priority)

        if primary_type.lower() != settings.jira_issue_type.lower():
            default_type_fields = self._build_fields(
                summary=summary,
                description=description,
                priority=None,
                labels=labels,
                issue_type=settings.jira_issue_type,
            )
            if default_type_fields not in attempts:
                attempts.append(default_type_fields)

        if primary_type.lower() != "task" and settings.jira_issue_type.lower() != "task":
            task_fields = self._build_fields(
                summary=summary,
                description=description,
                priority=None,
                labels=labels,
                issue_type="Task",
            )
            if task_fields not in attempts:
                attempts.append(task_fields)

        last_error: Optional[JiraError] = None
        for fields in attempts:
            try:
                return self._submit_issue(fields)
            except JiraError as exc:
                last_error = exc
                logger.warning(
                    "jira_create_retry",
                    extra={
                        "issuetype": fields.get("issuetype", {}).get("name"),
                        "has_priority": "priority" in fields,
                        "error": str(exc),
                    },
                )

        assert last_error is not None
        raise last_error

    def find_existing_ticket(self, request: InvestigateRequest) -> Optional[ExistingInvestigation]:
        """Find the newest JIRA ticket for this error fingerprint, if any."""
        settings = self._settings
        if not settings.jira_base_url or not settings.jira_email or not settings.jira_api_token:
            return None

        fp_label = investigation_fingerprint_label(
            request.error_message, request.service, request.environment
        )
        jql = (
            f'project = "{settings.jira_project_key}" AND labels = deployguard '
            f'AND labels = "{fp_label}" ORDER BY created DESC'
        )

        try:
            response = httpx.get(
                _jira_api_url(self._rest_base, "/rest/api/3/search/jql"),
                params={"jql": jql, "maxResults": 1, "fields": "summary,status"},
                auth=self._auth(),
                timeout=10.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise JiraError(f"JIRA search failed: {exc}") from exc

        issues = response.json().get("issues", [])
        if not issues:
            return None

        issue = issues[0]
        ticket_key = issue["key"]
        return ExistingInvestigation(
            jira_ticket=ticket_key,
            jira_url=_jira_browse_url(settings, ticket_key),
        )

    def create_ticket(self, request: InvestigateRequest, rca: BedrockRcaOutput) -> tuple[str, str]:
        summary = f"[{request.service}] {rca.root_cause}"[:255]
        issue_type = _derive_issue_type(rca, self._settings)
        try:
            ticket_key, ticket_url = self._create_issue_with_fallbacks(
                summary=summary,
                description=_build_description(rca),
                priority=_derive_priority(request, rca.confidence),
                labels=_issue_labels(request),
                issue_type=issue_type,
            )
        except JiraError:
            raise
        except httpx.HTTPError as exc:
            raise JiraError(f"JIRA ticket creation failed: {exc}") from exc

        if self._settings.jira_default_watchers:
            self._add_watchers(ticket_key, self._settings.jira_default_watchers)

        return ticket_key, ticket_url

    def _add_watchers(self, ticket_key: str, watchers: list[str]) -> None:
        settings = self._settings
        for account_id in watchers:
            try:
                response = httpx.post(
                    _jira_api_url(self._rest_base, f"/rest/api/3/issue/{ticket_key}/watchers"),
                    json=account_id,
                    auth=(settings.jira_email, settings.jira_api_token),
                    timeout=10.0,
                )
                response.raise_for_status()
            except httpx.HTTPError:
                logger.exception("jira_add_watcher_failed", extra={"ticket_key": ticket_key, "account_id": account_id})

    def create_ticket_raw(
        self,
        summary: str,
        description: str,
        priority: str = "Medium",
        labels: list[str] | None = None,
        issue_type: str | None = None,
    ) -> tuple[str, str]:
        """Create a JIRA ticket from raw parameters (used by AgentCore tool executor)."""
        try:
            return self._create_issue_with_fallbacks(
                summary=summary,
                description=plain_text_to_adf(description),
                priority=priority,
                labels=labels or ["deployguard"],
                issue_type=issue_type,
            )
        except JiraError:
            raise
        except httpx.HTTPError as exc:
            raise JiraError(f"JIRA ticket creation failed: {exc}") from exc
