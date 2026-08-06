"""Amazon Bedrock Agent invocation (FR-3, NFR-6, NFR-7).

Retrieval (Code + Metrics Knowledge Bases, top-K, metadata filtering) and
the system prompt/output-schema instructions are configured on the Bedrock
Agent itself (NFR-2, NFR-3) — this module only sends the dynamic error
fields and parses the structured JSON the agent returns (NFR-4).
"""
from __future__ import annotations

import json
import re

import boto3
from botocore.exceptions import ClientError

from app.config import Settings
from app.core.logging_config import get_logger
from app.core.retry import retry_with_backoff
from app.models.schemas import BedrockRcaOutput

logger = get_logger(__name__)


class BedrockInvocationError(Exception):
    """Raised when the Bedrock agent fails after retries or returns unusable output."""


class ThrottlingError(Exception):
    """Retryable Bedrock throttling condition."""


class BedrockAgentClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = boto3.client("bedrock-agent-runtime", region_name=settings.aws_region)
        # Control-plane client, used only for cheap metadata checks (health check) —
        # invoking the agent itself would burn tokens on every /health poll.
        self._control_client = boto3.client("bedrock-agent", region_name=settings.aws_region)

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
        try:
            response = self._client.invoke_agent(
                agentId=self._settings.bedrock_agent_id,
                agentAliasId=self._settings.bedrock_agent_alias_id,
                sessionId=session_id,
                inputText=input_text,
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("throttlingException", "ThrottlingException"):
                raise ThrottlingError(str(exc)) from exc
            raise

        chunks: list[str] = []
        for event in response["completion"]:
            chunk = event.get("chunk")
            if chunk and "bytes" in chunk:
                chunks.append(chunk["bytes"].decode("utf-8"))
        return "".join(chunks)

    @staticmethod
    def _parse_output(raw_text: str) -> BedrockRcaOutput:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            raise BedrockInvocationError(f"No JSON object found in Bedrock response: {raw_text[:200]}")

        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise BedrockInvocationError(f"Malformed JSON from Bedrock: {exc}") from exc

        try:
            return BedrockRcaOutput.model_validate(data)
        except Exception as exc:  # pydantic ValidationError
            raise BedrockInvocationError(f"Bedrock output failed schema validation: {exc}") from exc

    def health_check(self) -> bool:
        """Cheap connectivity check — fetches agent metadata, does not invoke the model."""
        try:
            self._control_client.get_agent(agentId=self._settings.bedrock_agent_id)
            return True
        except ClientError:
            logger.exception("bedrock_health_check_failed")
            return False
