from unittest.mock import MagicMock, patch

from app.config import Settings
from app.models.schemas import InvestigateContext, InvestigateRequest
from app.services.bedrock import ToolExecutor
from app.services.github import GitHubClient, _normalize_repo, _service_name_candidates


def _request(**overrides):
    base = {
        "error_message": "NullPointerException: PAYMENT_URL is null",
        "service": "payment-api",
        "environment": "production",
    }
    base.update(overrides)
    return InvestigateRequest.model_validate(base)


def test_normalize_repo_accepts_url():
    assert _normalize_repo("https://github.com/aadish-wbd/deployGuard.git") == "aadish-wbd/deployGuard"
    assert _normalize_repo("aadish-wbd/deployGuard") == "aadish-wbd/deployGuard"


def test_service_name_candidates_include_api_suffix():
    assert "payment-api" in _service_name_candidates("payment-api")
    assert "billing-api" in _service_name_candidates("billing")


@patch("app.services.github.httpx.get")
def test_resolve_repo_from_org(mock_get):
    repo_response = MagicMock()
    repo_response.is_success = True
    repo_response.status_code = 200
    repo_response.json.return_value = {
        "items": [{"full_name": "discoveryinc-dci/payment-api", "name": "payment-api"}]
    }

    code_response = MagicMock()
    code_response.is_success = True
    code_response.status_code = 200
    code_response.json.return_value = {
        "total_count": 1,
        "items": [
            {
                "name": "PaymentHandler.java",
                "path": "src/PaymentHandler.java",
                "html_url": "https://github.com/discoveryinc-dci/payment-api/blob/main/src/PaymentHandler.java",
                "repository": {"full_name": "discoveryinc-dci/payment-api"},
                "text_matches": [{"fragment": "PAYMENT_URL is null at line 42"}],
            }
        ],
    }
    mock_get.side_effect = [repo_response, code_response]

    settings = Settings(
        github_token="ghp_test",
        github_search_orgs="discoveryinc-dci",
        kb_number_of_results=5,
    )
    request = _request()
    result = GitHubClient(settings).search_for_investigation(request)

    assert result["fallback"] is False
    assert result["matches"][0]["repo"] == "discoveryinc-dci/payment-api"
    assert mock_get.call_args_list[0].kwargs["params"]["q"] == "payment-api in:name org:discoveryinc-dci"


@patch("app.services.github.httpx.get")
def test_explicit_github_repo_from_payload(mock_get):
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "total_count": 1,
        "items": [
            {
                "name": "handler.py",
                "path": "app/handler.py",
                "html_url": "https://github.com/discoveryinc-dci/plans-demo/blob/main/app/handler.py",
                "repository": {"full_name": "discoveryinc-dci/plans-demo"},
                "text_matches": [{"fragment": "optimizer timeout"}],
            }
        ],
    }
    mock_get.return_value = mock_response

    settings = Settings(github_token="ghp_test", github_search_orgs="other-org")
    request = _request(
        context=InvestigateContext(github_repo="discoveryinc-dci/plans-demo"),
    )
    result = GitHubClient(settings).search_for_investigation(request)

    assert result["fallback"] is False
    assert mock_get.call_count == 1
    assert "repo:discoveryinc-dci/plans-demo" in mock_get.call_args.kwargs["params"]["q"]


@patch("app.services.github.httpx.get")
def test_fallback_when_no_repo_found(mock_get):
    repo_response = MagicMock()
    repo_response.is_success = True
    repo_response.status_code = 200
    repo_response.json.return_value = {"items": []}
    mock_get.return_value = repo_response

    settings = Settings(github_token="ghp_test", github_search_orgs="discoveryinc-dci")
    result = GitHubClient(settings).search_for_investigation(_request(service="unknown-service"))

    assert result["fallback"] is True
    assert result["status"] == "fallback"
    assert "Proceed with RCA" in result["message"]
    assert result["searched_orgs"] == ["discoveryinc-dci"]


@patch("app.services.github.httpx.get")
def test_format_investigation_context_uses_fallback_message(mock_get):
    repo_response = MagicMock()
    repo_response.is_success = True
    repo_response.status_code = 200
    repo_response.json.return_value = {"items": []}
    mock_get.return_value = repo_response

    settings = Settings(github_token="ghp_test", github_search_orgs="discoveryinc-dci")
    text = GitHubClient(settings).format_investigation_context(_request(service="missing-service"))

    assert "Proceed with RCA" in text


def test_search_code_skips_without_token():
    settings = Settings(github_token="", github_search_orgs="discoveryinc-dci")
    result = GitHubClient(settings).search_for_investigation(_request())

    assert result["status"] == "skipped"
    assert result["fallback"] is True


def test_tool_executor_uses_investigation_payload():
    github = MagicMock()
    github.search_for_investigation.return_value = {"status": "fallback", "fallback": True}
    executor = ToolExecutor(github_client=github)
    request = _request()

    executor.set_investigation_request(request)
    result = executor.execute("github_search", {"query": "PAYMENT_URL"})

    github.search_for_investigation.assert_called_once_with(request, query="PAYMENT_URL")
    assert result["fallback"] is True
