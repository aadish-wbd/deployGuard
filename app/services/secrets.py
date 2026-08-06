"""Load JIRA/Slack credentials from AWS Secrets Manager (NFR-8).

Credentials never live in code or request payloads. Set
``SECRETS_MANAGER_SECRET_ARN`` (or ``SECRETS_MANAGER_SECRET_NAME``) to a
secret holding JSON such as::

    {
      "jira_email": "...",
      "jira_api_token": "...",
      "slack_bot_token": "...",
      "github_token": "...",
      "databricks_client_id": "...",
      "databricks_client_secret": "..."
    }

``SecretId`` accepts a secret name or full ARN. Locally, leave the setting
unset and use ``.env`` instead — see RUNBOOK.md.
"""
from __future__ import annotations

import json
import os
from typing import Mapping

import boto3
from botocore.exceptions import ClientError

from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Secret JSON keys -> environment variable names consumed by app.config.Settings
_SECRET_TO_ENV: dict[str, str] = {
    "jira_email": "JIRA_EMAIL",
    "JIRA_EMAIL": "JIRA_EMAIL",
    "jira_api_token": "JIRA_API_TOKEN",
    "JIRA_API_TOKEN": "JIRA_API_TOKEN",
    "slack_bot_token": "SLACK_BOT_TOKEN",
    "SLACK_BOT_TOKEN": "SLACK_BOT_TOKEN",
    "github_token": "GITHUB_TOKEN",
    "GITHUB_TOKEN": "GITHUB_TOKEN",
    "databricks_token": "DATABRICKS_TOKEN",
    "databricks_client_id": "DATABRICKS_CLIENT_ID",
    "databricks_client_secret": "DATABRICKS_CLIENT_SECRET",
}

_DATABASE_SECRET_TO_ENV = {
    "host": "PGHOST",
    "port": "PGPORT",
    "username": "PGUSER",
    "password": "PGPASSWORD",
    "dbname": "PGDATABASE",
}


def fetch_app_credentials(secret_id: str, region: str) -> dict[str, str]:
    """Fetch app credentials from Secrets Manager.

    Args:
        secret_id: Secret name or full ARN (e.g.
            ``arn:aws:secretsmanager:us-east-1:123:secret:deployguard-dev/app-credentials-AbCdEf``).
        region: AWS region for the Secrets Manager client.

    Returns:
        Mapping of env var names (``JIRA_EMAIL``, etc.) to secret values.

    Raises:
        ClientError: If the secret cannot be retrieved.
        ValueError: If the secret payload is missing or not valid JSON.
    """
    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_id)

    try:
        raw = response["SecretString"]
    except KeyError as exc:
        raise ValueError(f"Secret {secret_id!r} has no SecretString payload") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Secret {secret_id!r} is not valid JSON") from exc

    if not isinstance(payload, Mapping):
        raise ValueError(f"Secret {secret_id!r} JSON must be an object")

    credentials: dict[str, str] = {}
    for secret_key, env_name in _SECRET_TO_ENV.items():
        value = payload.get(secret_key)
        if value is not None and str(value).strip():
            credentials[env_name] = str(value)

    return credentials


def load_secrets_into_env(secret_id: str, region: str) -> dict[str, str]:
    """Fetch a Secrets Manager secret and inject its values as env vars.

    Must run before ``app.config.get_settings()`` is first used for clients,
    since settings are cached for the process lifetime. On failure, logs the
    error and returns an empty dict without raising (startup continues with
    existing env / ``.env`` values).
    """
    try:
        credentials = fetch_app_credentials(secret_id, region)
    except ClientError:
        logger.exception("secrets_manager_fetch_failed", extra={"secret_id": secret_id})
        return {}
    except ValueError:
        logger.exception("secrets_manager_invalid_payload", extra={"secret_id": secret_id})
        return {}

    for env_name, value in credentials.items():
        os.environ[env_name] = value

    logger.info(
        "secrets_manager_loaded",
        extra={"secret_id": secret_id, "keys": sorted(credentials.keys())},
    )
    return credentials


def load_database_secret_into_env(secret_name: str, region: str) -> None:
    """Fetch Aurora credentials and inject PG* env vars before settings load."""
    try:
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_name)
    except ClientError:
        logger.exception("database_secret_fetch_failed", extra={"secret_name": secret_name})
        return

    try:
        payload = json.loads(response["SecretString"])
    except (KeyError, json.JSONDecodeError):
        logger.exception("database_secret_invalid_payload", extra={"secret_name": secret_name})
        return

    for secret_key, env_name in _DATABASE_SECRET_TO_ENV.items():
        if secret_key in payload and payload[secret_key] is not None:
            os.environ[env_name] = str(payload[secret_key])

    logger.info("database_secret_loaded", extra={"secret_name": secret_name})
