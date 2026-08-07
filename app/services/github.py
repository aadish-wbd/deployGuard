"""GitHub code search for Bedrock AgentCore github_search tool (FR-3).

Uses the GitHub Code Search API to retrieve relevant file paths and snippets
for RCA. Failures return structured errors to the agent — they must not block
/investigate (NFR-7).
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from app.config import Settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

_GITHUB_API = "https://api.github.com"


class GitHubError(Exception):
    pass


def _normalize_repo(repo: str) -> str:
    """Accept owner/repo or https://github.com/owner/repo(.git)."""
    cleaned = repo.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    if cleaned.startswith("https://github.com/"):
        cleaned = cleaned.removeprefix("https://github.com/")
    return cleaned


def _format_match(item: dict[str, Any]) -> dict[str, Any]:
    repository = item.get("repository") or {}
    match: dict[str, Any] = {
        "path": item.get("path"),
        "name": item.get("name"),
        "repo": repository.get("full_name"),
        "url": item.get("html_url"),
    }
    fragments: list[str] = []
    for text_match in item.get("text_matches") or []:
        fragment = text_match.get("fragment")
        if isinstance(fragment, str) and fragment.strip():
            fragments.append(fragment.strip())
    if fragments:
        match["snippets"] = fragments[:3]
    return match


class GitHubClient:
    def __init__(self, settings: Settings):
        self._settings = settings

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.github_token}",
            "Accept": "application/vnd.github.text-match+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def search_code(self, query: str, repo: Optional[str] = None) -> dict[str, Any]:
        """Search GitHub code and return compact matches for the agent."""
        if not self._settings.github_token:
            return {"status": "skipped", "reason": "GITHUB_TOKEN not configured"}

        cleaned_query = query.strip()
        if not cleaned_query:
            return {"status": "error", "error": "query is required"}

        target_repo = _normalize_repo(repo) if repo else self._settings.github_default_repo
        search_query = f"{cleaned_query} repo:{target_repo}" if target_repo else cleaned_query
        per_page = min(max(self._settings.kb_number_of_results, 1), 10)

        try:
            response = httpx.get(
                f"{_GITHUB_API}/search/code",
                params={"q": search_query, "per_page": per_page},
                headers=self._headers(),
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            raise GitHubError(f"GitHub search request failed: {exc}") from exc

        if response.status_code == 401:
            return {"status": "error", "error": "GitHub authentication failed (401)"}
        if response.status_code == 403:
            return {
                "status": "error",
                "error": "GitHub search forbidden (403) — check token scopes (repo) and rate limits",
            }
        if response.status_code == 422:
            return {
                "status": "error",
                "error": f"GitHub rejected search query: {response.text[:300]}",
            }
        if not response.is_success:
            return {
                "status": "error",
                "error": f"GitHub search failed ({response.status_code}): {response.text[:300]}",
            }

        payload = response.json()
        items = payload.get("items") or []
        matches = [_format_match(item) for item in items]

        logger.info(
            "github_search_complete",
            extra={
                "query": cleaned_query,
                "repo": target_repo or "(any)",
                "total_count": payload.get("total_count", 0),
                "returned": len(matches),
            },
        )

        return {
            "status": "search_complete",
            "query": cleaned_query,
            "repo": target_repo or None,
            "total_count": payload.get("total_count", 0),
            "matches": matches,
        }
