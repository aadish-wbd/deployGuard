from unittest.mock import MagicMock, patch

from app.config import Settings
from app.core.investigation_fingerprint import investigation_fingerprint_label
from app.models.schemas import InvestigateRequest
from app.services.jira import (
    JiraClient,
    _build_description,
    _derive_issue_type,
    _issue_labels,
    plain_text_to_adf,
    resolve_jira_rest_base,
)


def test_issue_labels_include_fingerprint():
    request = InvestigateRequest(
        error_message="NullPointerException: PAYMENT_URL is null",
        service="payment-api",
        environment="production",
        context={"deploy_sha": "abc123"},
    )

    labels = _issue_labels(request)

    assert "deployguard" in labels
    assert "payment-api" in labels
    assert investigation_fingerprint_label(
        request.error_message, request.service, request.environment
    ) in labels


def test_build_description_returns_adf_doc():
    from app.models.schemas import BedrockRcaOutput

    rca = BedrockRcaOutput(
        root_cause="PAYMENT_URL is null",
        confidence=0.88,
        evidence=["log line 1", "log line 2"],
        rca_summary="Missing env var in production.",
        suggested_fix="Restore PAYMENT_URL in config.",
        issue_type="Bug",
    )

    doc = _build_description(rca)

    assert doc["type"] == "doc"
    assert doc["version"] == 1
    assert any(node["type"] == "bulletList" for node in doc["content"])
    assert any(
        item["content"][0]["content"][0]["text"] == "log line 1"
        for item in next(n for n in doc["content"] if n["type"] == "bulletList")["content"]
    )


def test_resolve_jira_rest_base_uses_cloud_id_for_scoped_tokens():
    settings = Settings(
        jira_base_url="https://example.atlassian.net",
        jira_cloud_id="abc-123",
        jira_api_token="ATCTT-scoped-token",
    )
    assert resolve_jira_rest_base(settings) == "https://api.atlassian.com/ex/jira/abc-123"


def test_resolve_jira_rest_base_uses_site_for_classic_tokens():
    settings = Settings.model_validate(
        {
            "jira_base_url": "https://example.atlassian.net/",
            "jira_api_token": "ATATT3x-classic-token",
            "jira_cloud_id": "",
        }
    )
    assert resolve_jira_rest_base(settings) == "https://example.atlassian.net"


def test_plain_text_to_adf_parses_bullet_blocks():
    doc = plain_text_to_adf("Summary line\n\n- first\n- second")

    assert doc["type"] == "doc"
    bullet = next(node for node in doc["content"] if node["type"] == "bulletList")
    items = [item["content"][0]["content"][0]["text"] for item in bullet["content"]]
    assert items == ["first", "second"]


@patch("app.services.jira.httpx.get")
def test_find_existing_ticket_uses_search_jql_endpoint(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"issues": [{"key": "KAN-25"}]}
    mock_get.return_value = mock_response

    settings = Settings(
        jira_base_url="https://example.atlassian.net",
        jira_email="user@example.com",
        jira_api_token="token",
        jira_project_key="KAN",
    )
    request = InvestigateRequest(
        error_message="NullPointerException: PAYMENT_URL is null",
        service="payment-api",
        environment="production",
        context={"deploy_sha": "abc124"},
    )

    found = JiraClient(settings).find_existing_ticket(request)

    assert found is not None
    assert found.jira_ticket == "KAN-25"
    assert mock_get.call_count == 1
    assert "/rest/api/3/search/jql" in mock_get.call_args.args[0]


def test_derive_issue_type_uses_agent_output():
    from app.models.schemas import BedrockRcaOutput

    settings = Settings(jira_issue_type="Task")
    rca = BedrockRcaOutput(
        root_cause="Config drift",
        confidence=0.7,
        evidence=[],
        rca_summary="Rotate credentials manually.",
        suggested_fix="Update secret.",
        issue_type="Task",
    )

    assert _derive_issue_type(rca, settings) == "Task"


def test_derive_issue_type_heuristic_bug():
    from app.models.schemas import BedrockRcaOutput

    settings = Settings(jira_issue_type="Task")
    rca = BedrockRcaOutput(
        root_cause="NullPointerException in PaymentHandler",
        confidence=0.9,
        evidence=["stack trace"],
        rca_summary="Unhandled null reference caused 500 errors.",
        suggested_fix="Add null check.",
    )

    assert _derive_issue_type(rca, settings) == "Bug"


def test_derive_issue_type_heuristic_incident():
    from app.models.schemas import BedrockRcaOutput

    settings = Settings(jira_issue_type="Task")
    rca = BedrockRcaOutput(
        root_cause="Database cluster unavailable",
        confidence=0.95,
        evidence=["health checks failing"],
        rca_summary="Production outage affecting all users.",
        suggested_fix="Fail over to replica.",
    )

    assert _derive_issue_type(rca, settings) == "Incident"


@patch("app.services.jira.httpx.post")
def test_create_ticket_uses_rca_issue_type(mock_post):
    from app.models.schemas import BedrockRcaOutput

    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {"key": "UA-42"}
    mock_post.return_value = mock_response

    settings = Settings(
        jira_base_url="https://example.atlassian.net",
        jira_email="user@example.com",
        jira_api_token="token",
        jira_project_key="UA",
        jira_issue_type="Task",
    )
    request = InvestigateRequest(
        error_message="NullPointerException: PAYMENT_URL is null",
        service="payment-api",
        environment="production",
    )
    rca = BedrockRcaOutput(
        root_cause="NullPointerException in handler",
        confidence=0.9,
        evidence=["PaymentHandler.java:42"],
        rca_summary="Missing env var caused NPE.",
        suggested_fix="Restore env var.",
        issue_type="Bug",
    )

    ticket_key, ticket_url = JiraClient(settings).create_ticket(request, rca)

    assert ticket_key == "UA-42"
    assert ticket_url.endswith("/browse/UA-42")
    payload = mock_post.call_args.kwargs["json"]["fields"]
    assert payload["issuetype"]["name"] == "Bug"
