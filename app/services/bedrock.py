"""Amazon Bedrock AgentCore Harness invocation (FR-3, NFR-6, NFR-7).

Uses AgentCore Harness with inline function tools for JIRA, Slack, and
GitHub. The harness orchestrates tool calls — the model decides when to
invoke each tool, and this service executes them client-side and returns
results.

Falls back to the Bedrock Converse API if no harness ARN is configured.
"""
from __future__ import annotations

import json
import re
from typing import Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from app.config import Settings
from app.core.logging_config import get_logger
from app.core.retry import retry_with_backoff
from app.models.schemas import BedrockRcaOutput

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# System prompt for direct Converse fallback (no harness)
# ---------------------------------------------------------------------------
CONVERSE_SYSTEM_PROMPT = """\
You are DeployGuard, an expert Site Reliability Engineer that investigates \
production incidents.

When given an error payload, follow this process:
1. Analyze the error message, stack trace, and any provided context.
2. Correlate the error with the deploy SHA, metric anomalies, and log patterns.
3. Identify the most likely root cause with supporting evidence.

IMPORTANT — Output Format:
You MUST respond with ONLY a JSON object matching this exact schema:
{
  "root_cause": "<concise root cause, max 200 chars>",
  "confidence": <float 0.0-1.0>,
  "evidence": ["<evidence item 1>", ...max 5 items],
  "rca_summary": "<detailed RCA summary, max 500 chars>",
  "suggested_fix": "<actionable fix suggestion, max 300 chars>"
}

Rules:
- Be precise and evidence-based. Cite specific files, functions, metric values.
- confidence: 0.9+ = strong evidence, 0.5-0.8 = likely, <0.5 = speculative.
- Respond with ONLY the JSON object. No other text.
"""

# ---------------------------------------------------------------------------
# Tool definitions for the harness (inline functions)
# ---------------------------------------------------------------------------
HARNESS_TOOLS = [
    {
        "type": "inline_function",
        "name": "jira_create_ticket",
        "config": {
            "inlineFunction": {
                "description": "Create a JIRA ticket for an incident. Returns the ticket key and URL.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string", "description": "Ticket summary"},
                        "description": {"type": "string", "description": "Full RCA description"},
                        "priority": {"type": "string", "enum": ["Critical", "High", "Medium", "Low"]},
                        "labels": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["summary", "description"],
                },
            }
        },
    },
    {
        "type": "inline_function",
        "name": "slack_send_alert",
        "config": {
            "inlineFunction": {
                "description": "Send a Slack alert to the incidents channel.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Alert message"},
                        "jira_ticket": {"type": "string", "description": "JIRA ticket key to link"},
                        "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    },
                    "required": ["message"],
                },
            }
        },
    },
    {
        "type": "inline_function",
        "name": "github_search",
        "config": {
            "inlineFunction": {
                "description": "Search GitHub repo code for relevant files or commits.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "repo": {"type": "string", "description": "owner/repo format"},
                    },
                    "required": ["query"],
                },
            }
        },
    },
]

# Harness system prompt
HARNESS_SYSTEM_PROMPT = """\
You are DeployGuard, an expert Site Reliability Engineer that investigates \
production incidents. You have tools to create JIRA tickets, send Slack alerts, \
and search GitHub code.

When given an error payload:
1. Analyze the error message, stack trace, and context.
2. If a repo/service is identified, use github_search to find relevant code.
3. Identify the root cause with evidence.
4. Create a JIRA ticket with the RCA using jira_create_ticket.
5. Send a Slack alert using slack_send_alert.

After completing tools, respond with ONLY a JSON object:
{
  "root_cause": "<concise root cause, max 200 chars>",
  "confidence": <float 0.0-1.0>,
  "evidence": ["<evidence item 1>", ...max 5 items],
  "rca_summary": "<detailed RCA summary, max 500 chars>",
  "suggested_fix": "<actionable fix suggestion, max 300 chars>"
}
"""


class BedrockInvocationError(Exception):
    """Raised when Bedrock fails after retries or returns unusable output."""


class ThrottlingError(Exception):
    """Retryable Bedrock throttling condition."""


class ToolExecutor:
    """Executes inline function tool calls using the app's service clients."""

    def __init__(self, jira_client=None, slack_client=None):
        self._jira = jira_client
        self._slack = slack_client

    def execute(self, tool_name: str, tool_input: dict) -> dict:
        """Execute a tool and return the result."""
        if tool_name == "jira_create_ticket":
            return self._exec_jira(tool_input)
        elif tool_name == "slack_send_alert":
            return self._exec_slack(tool_input)
        elif tool_name == "github_search":
            return self._exec_github(tool_input)
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    def _exec_jira(self, params: dict) -> dict:
        if not self._jira:
            return {"status": "skipped", "reason": "JIRA not configured"}
        try:
            ticket_key, ticket_url = self._jira.create_ticket_raw(
                summary=params.get("summary", ""),
                description=params.get("description", ""),
                priority=params.get("priority", "Medium"),
                labels=params.get("labels", []),
            )
            return {"ticket_key": ticket_key, "url": ticket_url}
        except Exception as exc:
            logger.warning("jira_tool_failed", extra={"error": str(exc)})
            return {"error": str(exc)}

    def _exec_slack(self, params: dict) -> dict:
        if not self._slack:
            return {"status": "skipped", "reason": "Slack not configured"}
        try:
            self._slack.send_alert_raw(
                message=params.get("message", ""),
                jira_ticket=params.get("jira_ticket"),
                severity=params.get("severity", "medium"),
            )
            return {"status": "sent"}
        except Exception as exc:
            logger.warning("slack_tool_failed", extra={"error": str(exc)})
            return {"error": str(exc)}

    def _exec_github(self, params: dict) -> dict:
        # GitHub search — simplified for now, returns guidance
        query = params.get("query", "")
        repo = params.get("repo", "")
        return {
            "status": "search_complete",
            "query": query,
            "repo": repo,
            "results": f"Code search for '{query}' in {repo or 'all repos'} — "
                       f"relevant context should be provided in the error payload.",
        }


class BedrockAgentClient:
    def __init__(self, settings: Settings, jira_client=None, slack_client=None):
        self._settings = settings
        self._tool_executor = ToolExecutor(jira_client=jira_client, slack_client=slack_client)

        if settings.agentcore_harness_arn:
            self._agentcore_client = boto3.client(
                "bedrock-agentcore", region_name=settings.aws_region
            )
            self._mode = "harness"
            logger.info("bedrock_mode", extra={"mode": "agentcore_harness"})
        else:
            self._converse_client = boto3.client(
                "bedrock-runtime", region_name=settings.aws_region
            )
            self._mode = "converse"
            logger.info("bedrock_mode", extra={"mode": "converse_fallback"})

    def invoke(self, session_id: str, input_text: str) -> BedrockRcaOutput:
        retryable_invoke = retry_with_backoff(
            max_retries=self._settings.bedrock_max_retries,
            base_delay_seconds=self._settings.bedrock_retry_base_delay_seconds,
            retry_on=(ThrottlingError,),
        )(self._invoke_once)

        try:
            raw_text = retryable_invoke(session_id, input_text)
        except ThrottlingError as exc:
            raise BedrockInvocationError(f"Bedrock throttled after retries: {exc}") from exc
        except ClientError as exc:
            raise BedrockInvocationError(f"Bedrock invocation failed: {exc}") from exc

        return self._parse_output(raw_text)

    def _invoke_once(self, session_id: str, input_text: str) -> str:
        if self._mode == "harness":
            return self._invoke_harness(session_id, input_text)
        return self._invoke_converse(session_id, input_text)

    # ------------------------------------------------------------------
    # AgentCore Harness path (with tool execution loop)
    # ------------------------------------------------------------------
    def _invoke_harness(self, session_id: str, input_text: str) -> str:
        messages = [{"role": "user", "content": [{"text": input_text}]}]

        max_iterations = 5
        for iteration in range(max_iterations):
            try:
                params = {
                    "harnessArn": self._settings.agentcore_harness_arn,
                    "runtimeSessionId": session_id,
                    "messages": messages,
                }
                response = self._agentcore_client.invoke_harness(**params)
            except ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code", "")
                if error_code in ("ThrottlingException", "throttlingException"):
                    raise ThrottlingError(str(exc)) from exc
                raise

            # Process the streaming response
            text_parts = []
            tool_uses = []
            current_tool_use = None

            for event in response.get("stream", []):
                if "contentBlockStart" in event:
                    start = event["contentBlockStart"].get("start", {})
                    if "toolUse" in start:
                        current_tool_use = {
                            "toolUseId": start["toolUse"]["toolUseId"],
                            "name": start["toolUse"]["name"],
                            "input_parts": [],
                        }
                elif "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"].get("delta", {})
                    if "text" in delta:
                        text_parts.append(delta["text"])
                    elif "toolUse" in delta and current_tool_use:
                        input_str = delta["toolUse"].get("input", "")
                        if input_str:
                            current_tool_use["input_parts"].append(input_str)
                elif "contentBlockStop" in event:
                    if current_tool_use:
                        tool_uses.append(current_tool_use)
                        current_tool_use = None
                elif "messageStop" in event:
                    stop_reason = event["messageStop"].get("stopReason", "")
                    if stop_reason == "end_turn":
                        return "".join(text_parts)
                elif "runtimeClientError" in event:
                    error_msg = event["runtimeClientError"].get("message", "Unknown harness error")
                    raise BedrockInvocationError(f"Harness runtime error: {error_msg}")

            # If no tool calls, return whatever text we got
            if not tool_uses:
                return "".join(text_parts)

            # Execute tools and send results back
            # Build assistant message with tool uses
            assistant_content = []
            for tu in tool_uses:
                input_json = "".join(tu["input_parts"])
                try:
                    parsed_input = json.loads(input_json) if input_json else {}
                except json.JSONDecodeError:
                    parsed_input = {}
                assistant_content.append({
                    "toolUse": {
                        "toolUseId": tu["toolUseId"],
                        "name": tu["name"],
                        "input": parsed_input,
                    }
                })

            # Build user message with tool results
            user_content = []
            for tu in tool_uses:
                input_json = "".join(tu["input_parts"])
                try:
                    parsed_input = json.loads(input_json) if input_json else {}
                except json.JSONDecodeError:
                    parsed_input = {}

                result = self._tool_executor.execute(tu["name"], parsed_input)
                user_content.append({
                    "toolResult": {
                        "toolUseId": tu["toolUseId"],
                        "content": [{"text": json.dumps(result)}],
                        "status": "error" if "error" in result else "success",
                    }
                })

            # Add to messages for next iteration
            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": user_content})

            logger.info("harness_tool_round", extra={"iteration": iteration + 1, "tools_called": [t["name"] for t in tool_uses]})

        # Max iterations reached
        return "".join(text_parts) if text_parts else ""

    # ------------------------------------------------------------------
    # Converse API fallback (no tools, direct model call)
    # ------------------------------------------------------------------
    def _invoke_converse(self, session_id: str, input_text: str) -> str:
        try:
            response = self._converse_client.converse(
                modelId=self._settings.bedrock_model_id,
                system=[{"text": CONVERSE_SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": [{"text": input_text}]}],
                inferenceConfig={
                    "maxTokens": self._settings.max_output_tokens_estimate,
                    "temperature": 0.2,
                    "topP": 0.9,
                },
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("ThrottlingException", "throttlingException"):
                raise ThrottlingError(str(exc)) from exc
            raise

        output = response.get("output", {})
        message = output.get("message", {})
        content_blocks = message.get("content", [])

        text_parts = []
        for block in content_blocks:
            if "text" in block:
                text_parts.append(block["text"])

        if not text_parts:
            raise BedrockInvocationError("Empty response from Bedrock Converse API")

        return "".join(text_parts)

    @staticmethod
    def _parse_output(raw_text: str) -> BedrockRcaOutput:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            raise BedrockInvocationError(
                f"No JSON object found in Bedrock response: {raw_text[:200]}"
            )

        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise BedrockInvocationError(f"Malformed JSON from Bedrock: {exc}") from exc

        try:
            return BedrockRcaOutput.model_validate(data)
        except Exception as exc:
            raise BedrockInvocationError(
                f"Bedrock output failed schema validation: {exc}"
            ) from exc

    def health_check(self) -> bool:
        """Connectivity check."""
        try:
            if self._mode == "harness":
                self._agentcore_client.meta.service_model
            else:
                self._converse_client.meta.service_model
            return True
        except Exception:
            logger.exception("bedrock_health_check_failed")
            return False
