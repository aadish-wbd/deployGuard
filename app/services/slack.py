"""Slack alert on investigation completion (FR-5).

Failures here must never block the /investigate response (NFR-7) — callers
catch SlackError and set actions.slack_sent=false with the error logged.
"""
from __future__ import annotations

from typing import List, Optional

import httpx

from app.config import Settings
from app.models.schemas import BedrockRcaOutput, InvestigateRequest


class SlackError(Exception):
    pass


def _build_message(
    request: InvestigateRequest,
    rca: BedrockRcaOutput,
    jira_url: Optional[str],
    oncall_mentions: List[str],
) -> str:
    mentions = " ".join(f"<@{m}>" for m in oncall_mentions)
    lines = [
        f"*DeployGuard alert — {request.service} ({request.environment})*",
        f"Root cause: {rca.root_cause}",
        f"Confidence: {rca.confidence:.0%}",
    ]
    if jira_url:
        lines.append(f"JIRA: {jira_url}")
    if mentions:
        lines.append(mentions)
    return "\n".join(lines)


class SlackClient:
    def __init__(self, settings: Settings):
        self._settings = settings

    def send_alert(
        self,
        request: InvestigateRequest,
        rca: BedrockRcaOutput,
        jira_url: Optional[str],
    ) -> None:
        settings = self._settings
        text = _build_message(request, rca, jira_url, settings.slack_oncall_mentions)

        try:
            response = httpx.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
                json={"channel": settings.slack_channel, "text": text},
                timeout=10.0,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise SlackError(f"Slack request failed: {exc}") from exc

        if not body.get("ok"):
            raise SlackError(f"Slack API error: {body.get('error')}")

    def send_alert_raw(
        self, message: str, jira_ticket: Optional[str] = None, severity: str = "medium"
    ) -> None:
        """Send a Slack alert from raw parameters (used by AgentCore tool executor)."""
        settings = self._settings
        mentions = " ".join(f"<@{m}>" for m in settings.slack_oncall_mentions)
        lines = [message]
        if jira_ticket:
            lines.append(f"JIRA: {settings.jira_base_url}/browse/{jira_ticket}" if settings.jira_base_url else f"JIRA: {jira_ticket}")
        if mentions:
            lines.append(mentions)
        text = "\n".join(lines)

        try:
            response = httpx.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
                json={"channel": settings.slack_channel, "text": text},
                timeout=10.0,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise SlackError(f"Slack request failed: {exc}") from exc

        if not body.get("ok"):
            raise SlackError(f"Slack API error: {body.get('error')}")
