"""Load JIRA/Slack/GitHub credentials from AWS Secrets Manager (NFR-8).

Credentials never live in code or request payloads. In AWS, set
SECRETS_MANAGER_SECRET_NAME to a secret holding a JSON blob such as:

    {
      "jira_email": "...",
      "jira_api_token": "...",
      "slack_bot_token": "...",
      "databricks_client_id": "...",
      "databricks_client_secret": "..."
    }

Locally (no AWS creds / secret name unset), these env vars are read
straight from `.env` for developer convenience — see RUNBOOK.md.
"""
import json
import os

import boto3
from botocore.exceptions import ClientError

from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Secret JSON keys -> environment variable names consumed by app.config.Settings
_SECRET_TO_ENV = {
    "jira_email": "JIRA_EMAIL",
    "jira_api_token": "JIRA_API_TOKEN",
    "slack_bot_token": "SLACK_BOT_TOKEN",
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


def load_secrets_into_env(secret_name: str, region: str) -> None:
    """Fetch a Secrets Manager secret and inject its values as env vars.

    Must run before app.config.get_settings() is first called, since that
    result is cached for the process lifetime.
    """
    try:
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_name)
    except ClientError:
        logger.exception("secrets_manager_fetch_failed", extra={"secret_name": secret_name})
        return

    try:
        payload = json.loads(response["SecretString"])
    except (KeyError, json.JSONDecodeError):
        logger.exception("secrets_manager_invalid_payload", extra={"secret_name": secret_name})
        return

    for secret_key, env_name in _SECRET_TO_ENV.items():
        if secret_key in payload:
            os.environ[env_name] = payload[secret_key]

    logger.info("secrets_manager_loaded", extra={"secret_name": secret_name})


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
