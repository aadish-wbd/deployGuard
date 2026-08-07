from unittest.mock import MagicMock, patch

from app.config import Settings
from app.services.bedrock import ToolExecutor
from app.services.github import GitHubClient, _normalize_repo


def test_normalize_repo_accepts_url():
    assert _normalize_repo("https://github.com/aadish-wbd/deployGuard.git") == "aadish-wbd/deployGuard"
    assert _normalize_repo("aadish-wbd/deployGuard") == "aadish-wbd/deployGuard"


@patch("app.services.github.httpx.get")
def test_search_code_returns_matches(mock_get):
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "total_count": 1,
        "items": [
            {
                "name": "PaymentHandler.java",
                "path": "src/PaymentHandler.java",
                "html_url": "https://github.com/acme/payments/blob/main/src/PaymentHandler.java",
                "repository": {"full_name": "acme/payments"},
                "text_matches": [{"fragment": "PAYMENT_URL is null at line 42"}],
            }
        ],
    }
    mock_get.return_value = mock_response

    settings = Settings(github_token="ghp_test", github_default_repo="acme/payments", kb_number_of_results=5)
    result = GitHubClient(settings).search_code("PAYMENT_URL", repo="acme/payments")

    assert result["status"] == "search_complete"
    assert result["total_count"] == 1
    assert result["matches"][0]["path"] == "src/PaymentHandler.java"
    assert "PAYMENT_URL" in result["matches"][0]["snippets"][0]
    assert mock_get.call_args.kwargs["params"]["q"] == "PAYMENT_URL repo:acme/payments"


def test_search_code_skips_without_token():
    settings = Settings(github_token="", github_default_repo="acme/payments")
    result = GitHubClient(settings).search_code("PAYMENT_URL")

    assert result["status"] == "skipped"


@patch("app.services.github.httpx.get")
def test_search_code_uses_default_repo(mock_get):
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200
    mock_response.json.return_value = {"total_count": 0, "items": []}
    mock_get.return_value = mock_response

    settings = Settings(github_token="ghp_test", github_default_repo="aadish-wbd/deployGuard")
    GitHubClient(settings).search_code("deployguard")

    assert mock_get.call_args.kwargs["params"]["q"] == "deployguard repo:aadish-wbd/deployGuard"


def test_tool_executor_calls_github_client():
    github = MagicMock()
    github.search_code.return_value = {"status": "search_complete", "matches": []}
    executor = ToolExecutor(github_client=github)

    result = executor.execute("github_search", {"query": "NullPointerException", "repo": "acme/app"})

    github.search_code.assert_called_once_with(query="NullPointerException", repo="acme/app")
    assert result["status"] == "search_complete"
