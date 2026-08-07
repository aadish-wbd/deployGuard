"""Startup debug helper — prints loaded config with secrets masked."""
from __future__ import annotations

import os
from typing import Optional

from app.config import Settings

# Env vars that commonly get stuck in the shell after `set -a && source .env`
_TRACKED_ENV_KEYS = (
    "SECRETS_MANAGER_SECRET_ARN",
    "SECRETS_MANAGER_SECRET_NAME",
    "AGENTCORE_HARNESS_ARN",
    "JIRA_BASE_URL",
    "JIRA_CLOUD_ID",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
    "JIRA_PROJECT_KEY",
    "JIRA_ISSUE_TYPE",
    "ENABLE_JIRA",
    "ENABLE_SLACK",
    "SLACK_CHANNEL",
    "SLACK_BOT_TOKEN",
    "GITHUB_TOKEN",
    "GITHUB_DEFAULT_REPO",
    "GITHUB_SEARCH_ORGS",
)


def _mask(value: str, prefix_len: int = 4) -> str:
    if not value:
        return "(not set)"
    if len(value) <= prefix_len:
        return f"*** ({len(value)} chars)"
    return f"{value[:prefix_len]}... ({len(value)} chars)"


def _env_source(key: str) -> str:
    return "shell/process env" if key in os.environ else ".env or default"


def print_loaded_config(
    settings: Settings,
    *,
    secrets_loaded: bool = False,
    secret_id: Optional[str] = None,
) -> None:
    """Print effective settings to stdout (tokens masked). For local debugging only."""
    print("\n=== DeployGuard loaded config ===")
    print("Note: shell/process env beats .env file (pydantic-settings priority).")
    if secret_id:
        status = "loaded" if secrets_loaded else "configured but failed to load"
        print(f"SECRETS_MANAGER: {status} [{_env_source('SECRETS_MANAGER_SECRET_ARN')}]")
        print(f"  secret_id: {secret_id}")
    else:
        print("SECRETS_MANAGER: (not configured — using .env / process env)")

    print(f"AWS_REGION: {settings.aws_region}")
    print(f"BEDROCK_MODEL_ID: {settings.bedrock_model_id}")
    harness = settings.agentcore_harness_arn
    print(
        f"AGENTCORE_HARNESS_ARN: {_mask(harness) if harness else '(not set — Converse fallback)'}"
        f" [{_env_source('AGENTCORE_HARNESS_ARN')}]"
    )
    print(f"ENABLE_JIRA: {settings.enable_jira} [{_env_source('ENABLE_JIRA')}]")
    print(f"JIRA_BASE_URL: {settings.jira_base_url or '(not set)'} [{_env_source('JIRA_BASE_URL')}]")
    if settings.jira_cloud_id:
        print(f"JIRA_CLOUD_ID: {settings.jira_cloud_id}")
    elif settings.jira_api_token.startswith("ATCTT"):
        print("JIRA_API: scoped token detected — using api.atlassian.com gateway (auto cloud ID)")
    else:
        print("JIRA_API: site URL (classic token)")
    print(f"JIRA_EMAIL: {settings.jira_email or '(not set)'} [{_env_source('JIRA_EMAIL')}]")
    print(f"JIRA_API_TOKEN: {_mask(settings.jira_api_token)} [{_env_source('JIRA_API_TOKEN')}]")
    print(f"JIRA_PROJECT_KEY: {settings.jira_project_key} [{_env_source('JIRA_PROJECT_KEY')}]")
    print(f"JIRA_ISSUE_TYPE: {settings.jira_issue_type}")

    print(f"ENABLE_SLACK: {settings.enable_slack} [{_env_source('ENABLE_SLACK')}]")
    print(f"SLACK_CHANNEL: {settings.slack_channel} [{_env_source('SLACK_CHANNEL')}]")
    print(f"SLACK_BOT_TOKEN: {_mask(settings.slack_bot_token)} [{_env_source('SLACK_BOT_TOKEN')}]")
    print(f"GITHUB_TOKEN: {_mask(settings.github_token)} [{_env_source('GITHUB_TOKEN')}]")
    print(
        f"GITHUB_DEFAULT_REPO: {settings.github_default_repo or '(not set)'}"
        f" [{_env_source('GITHUB_DEFAULT_REPO')}]"
    )
    print(
        f"GITHUB_SEARCH_ORGS: {settings.github_search_orgs or '(not set)'}"
        f" [{_env_source('GITHUB_SEARCH_ORGS')}]"
    )

    stale = [key for key in _TRACKED_ENV_KEYS if key in os.environ]
    if stale:
        print("\nShell exports detected (override .env until unset or terminal restarted):")
        for key in stale:
            value = os.environ[key]
            if "TOKEN" in key or "SECRET" in key:
                display = _mask(value)
            else:
                display = value
            print(f"  {key}={display}")
    print("=================================\n")
