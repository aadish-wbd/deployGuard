"""GitHub code search for RCA (FR-3).

Resolves application repositories across configured GitHub organizations using
fields from POST /investigate (service name, optional github_org/github_repo).
When no repository or code match is found, returns an explicit fallback so the
agent continues with payload-only RCA instead of inventing file paths.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import httpx

from app.config import Settings
from app.core.logging_config import get_logger
from app.models.schemas import InvestigateRequest

logger = get_logger(__name__)

_GITHUB_API = "https://api.github.com"
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_STACK_FRAME_RE = re.compile(r"(?:at\s+)?(?:[\w.$]+\.)?([A-Z][\w$]+(?:\.java|\.py|\.ts|\.go)?)", re.MULTILINE)


class GitHubError(Exception):
    pass


def _normalize_repo(repo: str) -> str:
    cleaned = repo.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    if cleaned.startswith("https://github.com/"):
        cleaned = cleaned.removeprefix("https://github.com/")
    return cleaned


def _service_name_candidates(service: str) -> list[str]:
    base = service.strip().lower().replace("_", "-")
    candidates = [base]
    if not base.endswith("-api"):
        candidates.append(f"{base}-api")
    if not base.endswith("-service"):
        candidates.append(f"{base}-service")
    original = service.strip().lower()
    if original and original not in candidates:
        candidates.append(original)
    return list(dict.fromkeys(candidates))


def _extract_identifiers(text: str) -> list[str]:
    tokens = _IDENTIFIER_RE.findall(text or "")
    stopwords = {"the", "and", "for", "with", "from", "error", "exception", "failed", "null"}
    seen: set[str] = set()
    results: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in stopwords or len(token) < 4:
            continue
        if lowered not in seen:
            seen.add(lowered)
            results.append(token)
    return results[:5]


def _build_code_queries(request: InvestigateRequest) -> list[str]:
    queries: list[str] = []
    for token in _extract_identifiers(request.error_message):
        queries.append(token)
    if request.stack_trace:
        for match in _STACK_FRAME_RE.finditer(request.stack_trace):
            symbol = match.group(1)
            if symbol and symbol not in queries:
                queries.append(symbol)
    if not queries:
        queries.append(request.service.replace("-", " "))
    return queries[:3]


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

    def _fallback_response(
        self,
        request: InvestigateRequest,
        *,
        orgs: list[str],
        resolution: str,
        detail: str,
        status: str = "fallback",
    ) -> dict[str, Any]:
        org_label = ", ".join(orgs) if orgs else "(none configured)"
        return {
            "status": status,
            "fallback": True,
            "message": (
                f"{detail} "
                f"Proceed with RCA using the error message, stack trace, and logs only — "
                "do not invent file paths or code references."
            ),
            "searched_orgs": orgs,
            "service": request.service,
            "resolution": resolution,
        }

    def resolve_search_orgs(self, request: InvestigateRequest) -> list[str]:
        ctx = request.context
        if ctx and ctx.github_org:
            return [ctx.github_org.strip()]
        return list(self._settings.github_search_org_list())

    def resolve_repositories(self, request: InvestigateRequest) -> tuple[list[str], list[str], str]:
        """Return candidate repos, orgs searched, and a resolution note."""
        ctx = request.context
        if ctx and ctx.github_repo:
            repo = _normalize_repo(ctx.github_repo)
            org = repo.split("/", 1)[0] if "/" in repo else (ctx.github_org or "")
            orgs = [org] if org else self.resolve_search_orgs(request)
            return [repo], orgs, "explicit github_repo from investigate payload"

        orgs = self.resolve_search_orgs(request)
        repos: list[str] = []
        for org in orgs:
            found = self._find_repo_in_org(org, request.service)
            if found and found not in repos:
                repos.append(found)

        if repos:
            return repos, orgs, f"matched service {request.service!r} in org(s) {', '.join(orgs)}"

        if self._settings.github_default_repo:
            fallback_repo = _normalize_repo(self._settings.github_default_repo)
            fallback_org = fallback_repo.split("/", 1)[0]
            merged_orgs = orgs[:]
            if fallback_org and fallback_org not in merged_orgs:
                merged_orgs.append(fallback_org)
            return [fallback_repo], merged_orgs, "fallback to configured github_default_repo"

        return [], orgs, "no repository resolved"

    def _find_repo_in_org(self, org: str, service: str) -> Optional[str]:
        org_name = org.strip()
        if not org_name:
            return None

        for candidate in _service_name_candidates(service):
            try:
                response = httpx.get(
                    f"{_GITHUB_API}/search/repositories",
                    params={"q": f"{candidate} in:name org:{org_name}", "per_page": 5},
                    headers={**self._headers(), "Accept": "application/vnd.github+json"},
                    timeout=10.0,
                )
            except httpx.HTTPError as exc:
                raise GitHubError(f"GitHub repository search failed: {exc}") from exc

            if not response.is_success:
                logger.warning(
                    "github_repo_search_failed",
                    extra={"org": org_name, "service": service, "status": response.status_code},
                )
                continue

            for item in response.json().get("items") or []:
                full_name = item.get("full_name")
                name = (item.get("name") or "").lower()
                if full_name and (name == candidate or candidate in name):
                    return full_name
        return None

    def _search_code_query(
        self,
        query: str,
        *,
        repo: Optional[str] = None,
        org: Optional[str] = None,
    ) -> dict[str, Any]:
        cleaned_query = query.strip()
        if not cleaned_query:
            return {"status": "error", "error": "query is required", "matches": []}

        qualifiers: list[str] = []
        if repo:
            qualifiers.append(f"repo:{_normalize_repo(repo)}")
        elif org:
            qualifiers.append(f"org:{org.strip()}")

        search_query = " ".join([cleaned_query, *qualifiers]).strip()
        per_page = min(max(self._settings.kb_number_of_results, 1), 10)

        try:
            response = httpx.get(
                f"{_GITHUB_API}/search/code",
                params={"q": search_query, "per_page": per_page},
                headers=self._headers(),
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            raise GitHubError(f"GitHub code search request failed: {exc}") from exc

        if response.status_code == 401:
            return {"status": "error", "error": "GitHub authentication failed (401)", "matches": []}
        if response.status_code == 403:
            return {
                "status": "error",
                "error": "GitHub search forbidden (403) — check token scopes (repo) and rate limits",
                "matches": [],
            }
        if response.status_code == 422:
            return {
                "status": "error",
                "error": f"GitHub rejected search query: {response.text[:300]}",
                "matches": [],
            }
        if not response.is_success:
            return {
                "status": "error",
                "error": f"GitHub search failed ({response.status_code}): {response.text[:300]}",
                "matches": [],
            }

        payload = response.json()
        items = payload.get("items") or []
        matches = [_format_match(item) for item in items]
        return {
            "status": "search_complete",
            "query": cleaned_query,
            "search_query": search_query,
            "repo": _normalize_repo(repo) if repo else None,
            "org": org.strip() if org else None,
            "total_count": payload.get("total_count", 0),
            "matches": matches,
        }

    def search_code(
        self,
        query: str,
        *,
        repo: Optional[str] = None,
        org: Optional[str] = None,
        request: Optional[InvestigateRequest] = None,
    ) -> dict[str, Any]:
        """Search code in an explicit repo/org or resolve targets from the investigation payload."""
        if not self._settings.github_token:
            return {"status": "skipped", "reason": "GITHUB_TOKEN not configured", "fallback": True}

        if request is not None and not repo and not org:
            return self.search_for_investigation(request, query=query)

        result = self._search_code_query(query, repo=repo, org=org)
        result["fallback"] = not bool(result.get("matches"))
        return result

    def search_for_investigation(
        self,
        request: InvestigateRequest,
        *,
        query: Optional[str] = None,
    ) -> dict[str, Any]:
        if not self._settings.github_token:
            return {"status": "skipped", "reason": "GITHUB_TOKEN not configured", "fallback": True}

        repos, orgs, resolution = self.resolve_repositories(request)
        queries = [query.strip()] if query and query.strip() else _build_code_queries(request)

        if not repos:
            return self._fallback_response(
                request,
                orgs=orgs,
                resolution=resolution,
                detail=(
                    f"No GitHub repository found for service {request.service!r} "
                    f"in org(s) {', '.join(orgs) if orgs else '(none configured)'}."
                ),
            )

        for repo in repos:
            for code_query in queries:
                result = self._search_code_query(code_query, repo=repo)
                if result.get("matches"):
                    result["fallback"] = False
                    result["resolution"] = resolution
                    result["repos_searched"] = repos
                    result["searched_orgs"] = orgs
                    logger.info(
                        "github_search_complete",
                        extra={
                            "service": request.service,
                            "repo": repo,
                            "query": code_query,
                            "matches": len(result["matches"]),
                        },
                    )
                    return result

        if orgs:
            for org in orgs:
                for code_query in queries:
                    result = self._search_code_query(code_query, org=org)
                    if result.get("matches"):
                        result["fallback"] = False
                        result["resolution"] = f"org-wide code search in {org}"
                        result["repos_searched"] = repos
                        result["searched_orgs"] = orgs
                        return result

        return self._fallback_response(
            request,
            orgs=orgs,
            resolution=resolution,
            status="no_code_matches",
            detail=(
                f"Repositories {repos} were resolved for service {request.service!r}, "
                "but GitHub code search returned no matches."
            ),
        )

    def format_investigation_context(self, request: InvestigateRequest) -> str:
        result = self.search_for_investigation(request)
        if result.get("fallback"):
            return result.get("message", "GitHub code search unavailable; use error payload only.")

        lines = [f"status: {result.get('status', 'search_complete')}"]
        if result.get("resolution"):
            lines.append(f"resolution: {result['resolution']}")
        if result.get("repo") or result.get("repos_searched"):
            lines.append(f"repos: {', '.join(result.get('repos_searched') or [result.get('repo')])}")
        for match in result.get("matches", [])[:5]:
            line = f"- {match.get('repo')}:{match.get('path')}"
            snippets = match.get("snippets") or []
            if snippets:
                line += f" — {snippets[0][:240]}"
            lines.append(line)
        return "\n".join(lines)
