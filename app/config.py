"""Central configuration for DeployGuard.

Values are read from environment variables (or a local .env file via
pydantic-settings). In AWS, secrets (JIRA/Slack/GitHub tokens) should be
pulled from Secrets Manager at startup via app.services.secrets and
injected as env vars — never hardcoded or passed in request payloads
(NFR-8).
"""
from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.limits import (
    MAX_ERROR_MESSAGE_CHARS,
    MAX_LOG_SNIPPET_CHARS,
    MAX_REQUEST_BODY_BYTES,
    MAX_STACK_TRACE_CHARS,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- AWS / Bedrock ---
    aws_region: str = "us-east-1"
    bedrock_agent_id: str = ""
    bedrock_agent_alias_id: str = "TSTALIASID"
    bedrock_max_retries: int = 3
    bedrock_retry_base_delay_seconds: float = 1.0

    # --- S3 persistence ---
    s3_bucket: str = "deployguard-incidents"
    s3_index_key: str = "index/incidents.jsonl"

    # --- Secrets Manager ---
    secrets_manager_secret_name: Optional[str] = None

    # --- JIRA ---
    enable_jira: bool = True
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = "OPS"
    jira_default_assignee: Optional[str] = None
    jira_default_watchers: List[str] = Field(default_factory=list)

    # --- Slack ---
    enable_slack: bool = True
    slack_bot_token: str = ""
    slack_channel: str = "#deployguard-alerts"
    slack_oncall_mentions: List[str] = Field(default_factory=list)

    # --- Databricks ---
    enable_databricks: bool = True
    databricks_host: str = ""
    databricks_token: str = ""
    databricks_client_id: str = ""
    databricks_client_secret: str = ""

    # --- Payload / cost guardrails (NFR-10, payload limits) ---
    max_error_message_chars: int = MAX_ERROR_MESSAGE_CHARS
    max_stack_trace_chars: int = MAX_STACK_TRACE_CHARS
    max_log_snippet_chars: int = MAX_LOG_SNIPPET_CHARS
    max_request_body_bytes: int = MAX_REQUEST_BODY_BYTES
    max_input_tokens_estimate: int = 2000
    max_output_tokens_estimate: int = 800

    # --- Caching / dedup (NFR-5) ---
    dedup_cache_ttl_seconds: int = 300

    # --- Performance (NFR-6) ---
    investigate_soft_timeout_seconds: int = 90
    client_timeout_seconds: int = 120

    # --- Cost control (NFR-10) ---
    daily_investigation_cap: Optional[int] = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
