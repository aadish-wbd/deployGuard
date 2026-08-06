import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.config import Settings
from app.services.databricks import DatabricksClient, DatabricksError


def _settings(**overrides) -> Settings:
    base = {
        "databricks_host": "https://example.cloud.databricks.com",
    }
    base.update(overrides)
    return Settings(**base)


def test_configured_with_oauth_creds():
    client = DatabricksClient(
        _settings(databricks_client_id="sp-id", databricks_client_secret="sp-secret")
    )
    assert client.configured is True


def test_configured_with_pat_only():
    client = DatabricksClient(_settings(databricks_token="dapi123"))
    assert client.configured is True


def test_not_configured_without_auth():
    client = DatabricksClient(_settings())
    assert client.configured is False


@patch("app.services.databricks.httpx.post")
@patch("app.services.databricks.httpx.request")
def test_oauth_token_fetched_and_cached(mock_request, mock_post):
    oauth_response = MagicMock()
    oauth_response.raise_for_status = MagicMock()
    oauth_response.json.return_value = {"access_token": "oauth-token", "expires_in": 3600}
    mock_post.return_value = oauth_response

    api_response = MagicMock()
    api_response.raise_for_status = MagicMock()
    api_response.content = b'{"job_id": 42}'
    api_response.json.return_value = {"job_id": 42}
    mock_request.return_value = api_response

    client = DatabricksClient(
        _settings(databricks_client_id="sp-id", databricks_client_secret="sp-secret")
    )
    client.get_run("123")
    client.get_run("456")

    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs["auth"] == ("sp-id", "sp-secret")
    assert mock_request.call_count == 2
    assert mock_request.call_args.kwargs["headers"]["Authorization"] == "Bearer oauth-token"


@patch("app.services.databricks.httpx.post")
@patch("app.services.databricks.httpx.request")
def test_oauth_token_refreshed_when_near_expiry(mock_request, mock_post):
    def make_oauth_response(token: str):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {"access_token": token, "expires_in": 3600}
        return response

    mock_post.side_effect = [
        make_oauth_response("token-1"),
        make_oauth_response("token-2"),
    ]

    api_response = MagicMock()
    api_response.raise_for_status = MagicMock()
    api_response.content = b'{"job_id": 1}'
    api_response.json.return_value = {"job_id": 1}
    mock_request.return_value = api_response

    client = DatabricksClient(
        _settings(databricks_client_id="sp-id", databricks_client_secret="sp-secret")
    )
    client.get_run("1")
    client._oauth_token_expires_at = time.monotonic() + 60
    client.get_run("2")

    assert mock_post.call_count == 2
    assert mock_request.call_args.kwargs["headers"]["Authorization"] == "Bearer token-2"


@patch("app.services.databricks.httpx.request")
def test_pat_used_when_oauth_not_configured(mock_request):
    api_response = MagicMock()
    api_response.raise_for_status = MagicMock()
    api_response.content = b'{"job_id": 7}'
    api_response.json.return_value = {"job_id": 7}
    mock_request.return_value = api_response

    client = DatabricksClient(_settings(databricks_token="dapi-static"))
    client.get_run("99")

    mock_request.assert_called_once()
    assert mock_request.call_args.kwargs["headers"]["Authorization"] == "Bearer dapi-static"


@patch("app.services.databricks.httpx.post")
def test_oauth_failure_raises_databricks_error(mock_post):
    response = MagicMock()
    response.text = "invalid_client"
    mock_post.side_effect = httpx.HTTPStatusError(
        "401",
        request=MagicMock(),
        response=response,
    )

    client = DatabricksClient(
        _settings(databricks_client_id="sp-id", databricks_client_secret="bad-secret")
    )

    with pytest.raises(DatabricksError, match="OAuth token request failed"):
        client.get_run("1")
