"""Unit tests for AWS Secrets Manager credential loading."""
import os
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

from app.services.secrets import fetch_app_credentials, load_secrets_into_env


SECRET_ARN = "arn:aws:secretsmanager:us-east-1:657246005217:secret:deployguard-dev/app-credentials-t99KAJ"

SECRET_JSON = """{
  "jira_email": "user@example.com",
  "jira_api_token": "jira-token",
  "slack_bot_token": "xoxb-slack-token"
}"""


@patch("app.services.secrets.boto3.client")
def test_fetch_app_credentials_maps_json_to_env_names(mock_boto_client):
    mock_boto_client.return_value.get_secret_value.return_value = {"SecretString": SECRET_JSON}

    credentials = fetch_app_credentials(SECRET_ARN, "us-east-1")

    assert credentials == {
        "JIRA_EMAIL": "user@example.com",
        "JIRA_API_TOKEN": "jira-token",
        "SLACK_BOT_TOKEN": "xoxb-slack-token",
    }
    mock_boto_client.return_value.get_secret_value.assert_called_once_with(SecretId=SECRET_ARN)


@patch("app.services.secrets.boto3.client")
def test_fetch_app_credentials_accepts_uppercase_json_keys(mock_boto_client):
    mock_boto_client.return_value.get_secret_value.return_value = {
        "SecretString": '{"JIRA_EMAIL":"a@b.com","JIRA_API_TOKEN":"tok","SLACK_BOT_TOKEN":"xoxb"}'
    }

    credentials = fetch_app_credentials(SECRET_ARN, "us-east-1")

    assert credentials["JIRA_EMAIL"] == "a@b.com"
    assert credentials["JIRA_API_TOKEN"] == "tok"
    assert credentials["SLACK_BOT_TOKEN"] == "xoxb"


@patch("app.services.secrets.boto3.client")
def test_fetch_app_credentials_raises_on_invalid_json(mock_boto_client):
    mock_boto_client.return_value.get_secret_value.return_value = {"SecretString": "not-json"}

    with pytest.raises(ValueError, match="not valid JSON"):
        fetch_app_credentials(SECRET_ARN, "us-east-1")


@patch("app.services.secrets.boto3.client")
def test_load_secrets_into_env_injects_env_vars(mock_boto_client, monkeypatch):
    mock_boto_client.return_value.get_secret_value.return_value = {"SecretString": SECRET_JSON}
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)

    loaded = load_secrets_into_env(SECRET_ARN, "us-east-1")

    assert loaded["JIRA_EMAIL"] == "user@example.com"
    assert os.environ["JIRA_API_TOKEN"] == "jira-token"
    assert os.environ["SLACK_BOT_TOKEN"] == "xoxb-slack-token"


@patch("app.services.secrets.boto3.client")
def test_load_secrets_into_env_returns_empty_on_client_error(mock_boto_client):
    mock_boto_client.return_value.get_secret_value.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
        "GetSecretValue",
    )

    assert load_secrets_into_env(SECRET_ARN, "us-east-1") == {}
