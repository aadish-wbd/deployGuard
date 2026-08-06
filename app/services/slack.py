"""Slack alert on investigation completion (FR-5).

Failures here must never block the /investigate response (NFR-7) — callers
catch SlackError and set actions.slack_sent=false with the error logged.
"""
from __future__ import annotations

from typing import List, Optional

import httpx

from app.config import Settings
from app.core.logging_config import get_logger
from app.models.schemas import BedrockRcaOutput, InvestigateRequest

logger = get_logger(__name__)

_NOT_IN_CHANNEL_HELP = (
    "Invite the bot to the channel (/invite @YourBotName) or add the "
    "chat:write.public bot scope for public channels."
)


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


def _channel_targets(channel: str) -> list[str]:
    """Try common Slack channel reference formats."""
    stripped = channel.strip()
    if not stripped:
        return [channel]

    targets = [stripped]
    if stripped.startswith("#"):
        targets.append(stripped[1:])
    elif stripped.startswith("C") and len(stripped) >= 9:
        pass  # channel ID — use as configured
    else:
        targets.append(f"#{stripped}")

    seen: set[str] = set()
    ordered: list[str] = []
    for item in targets:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


class SlackClient:
    def __init__(self, settings: Settings):
        self._settings = settings

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._settings.slack_bot_token}"}

    def _call_post_message(self, channel: str, text: str) -> dict:
        response = httpx.post(
            "https://slack.com/api/chat.postMessage",
            headers=self._headers(),
            json={"channel": channel, "text": text},
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()

    def _try_join_channel(self, channel_id: str) -> None:
        """Best-effort join when SLACK_CHANNEL is a channel ID (requires channels:join)."""
        response = httpx.post(
            "https://slack.com/api/conversations.join",
            headers=self._headers(),
            json={"channel": channel_id},
            timeout=10.0,
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("ok") and body.get("error") != "already_in_channel":
            raise SlackError(f"Slack API error: {body.get('error')} — {_NOT_IN_CHANNEL_HELP}")

    def _post_message(self, channel: str, text: str) -> None:
        last_error: Optional[str] = None
        channel_id = channel.strip()

        for target in _channel_targets(channel):
            body = self._call_post_message(target, text)
            if body.get("ok"):
                return
            last_error = body.get("error")
            if last_error == "missing_scope":
                raise SlackError(
                    "Slack API error: missing_scope — add bot scopes chat:write and "
                    "chat:write.public, then reinstall the app to your workspace."
                )
            if last_error not in {"not_in_channel", "channel_not_found"}:
                raise SlackError(f"Slack API error: {last_error}")

        # Optional join retry when user configured a channel ID directly
        if channel_id.startswith("C") and len(channel_id) >= 9:
            self._try_join_channel(channel_id)
            body = self._call_post_message(channel_id, text)
            if body.get("ok"):
                return
            last_error = body.get("error")

        raise SlackError(f"Slack API error: {last_error} — {_NOT_IN_CHANNEL_HELP}")

    def send_alert(
        self,
        request: InvestigateRequest,
        rca: BedrockRcaOutput,
        jira_url: Optional[str],
    ) -> None:
        settings = self._settings
        text = _build_message(request, rca, jira_url, settings.slack_oncall_mentions)
        try:
            self._post_message(settings.slack_channel, text)
        except httpx.HTTPError as exc:
            raise SlackError(f"Slack request failed: {exc}") from exc

    def send_alert_raw(
        self, message: str, jira_ticket: Optional[str] = None, severity: str = "medium"
    ) -> None:
        """Send a Slack alert from raw parameters (used by AgentCore tool executor)."""
        settings = self._settings
        mentions = " ".join(f"<@{m}>" for m in settings.slack_oncall_mentions)
        lines = [message]
        if jira_ticket:
            lines.append(
                f"JIRA: {settings.jira_base_url}/browse/{jira_ticket}"
                if settings.jira_base_url
                else f"JIRA: {jira_ticket}"
            )
        if mentions:
            lines.append(mentions)
        text = "\n".join(lines)

        try:
            self._post_message(settings.slack_channel, text)
        except httpx.HTTPError as exc:
            raise SlackError(f"Slack request failed: {exc}") from exc
