"""Databricks REST API client for job run inspection (FR-6).

Authenticates with OAuth M2M (service principal client ID + secret) when
configured, otherwise falls back to a workspace personal access token (PAT).
Credentials are stored in env / Secrets Manager (NFR-8).

Primary endpoints:
  - GET /api/2.1/jobs/runs/get
  - GET /api/2.1/jobs/runs/export
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from app.config import Settings
from app.core.logging_config import get_logger
from app.services.databricks_export import extract_failure_context

logger = get_logger(__name__)

# Refresh OAuth tokens this many seconds before they expire.
_OAUTH_REFRESH_BUFFER_SECONDS = 300


class DatabricksError(Exception):
    pass


class DatabricksClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._host = settings.databricks_host.rstrip("/") if settings.databricks_host else ""
        self._pat_token = settings.databricks_token
        self._client_id = settings.databricks_client_id
        self._client_secret = settings.databricks_client_secret
        self._oauth_token: Optional[str] = None
        self._oauth_token_expires_at: float = 0.0

    @property
    def configured(self) -> bool:
        if not self._host:
            return False
        return bool(self._uses_oauth or self._pat_token)

    @property
    def _uses_oauth(self) -> bool:
        return bool(self._client_id and self._client_secret)

    def _fetch_oauth_token(self) -> str:
        url = f"{self._host}/oidc/v1/token"
        try:
            response = httpx.post(
                url,
                auth=(self._client_id, self._client_secret),
                data={"grant_type": "client_credentials", "scope": "all-apis"},
                timeout=30.0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response is not None else str(exc)
            logger.error(
                "databricks_oauth_error",
                extra={"status": exc.response.status_code if exc.response else None, "detail": detail},
            )
            raise DatabricksError(f"Databricks OAuth token request failed: {detail}") from exc
        except httpx.HTTPError as exc:
            logger.exception("databricks_oauth_transport_error")
            raise DatabricksError(f"Databricks OAuth token request failed: {exc}") from exc

        payload = response.json()
        access_token = payload.get("access_token")
        if not access_token:
            raise DatabricksError("Databricks OAuth token response missing access_token")

        expires_in = int(payload.get("expires_in", 3600))
        self._oauth_token = access_token
        self._oauth_token_expires_at = time.monotonic() + expires_in
        logger.info("databricks_oauth_token_fetched", extra={"expires_in": expires_in})
        return access_token

    def _get_access_token(self) -> str:
        if self._uses_oauth:
            if self._oauth_token and time.monotonic() < (
                self._oauth_token_expires_at - _OAUTH_REFRESH_BUFFER_SECONDS
            ):
                return self._oauth_token
            return self._fetch_oauth_token()

        if self._pat_token:
            return self._pat_token

        raise DatabricksError(
            "Databricks is not configured "
            "(set DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET or DATABRICKS_TOKEN)"
        )

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> dict:
        if not self.configured:
            raise DatabricksError(
                "Databricks is not configured "
                "(set DATABRICKS_HOST and DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET or DATABRICKS_TOKEN)"
            )

        url = f"{self._host}{path}"
        try:
            response = httpx.request(
                method,
                url,
                headers=self._headers(),
                params=params,
                timeout=timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response is not None else str(exc)
            logger.error(
                "databricks_api_error",
                extra={"path": path, "status": exc.response.status_code if exc.response else None, "detail": detail},
            )
            raise DatabricksError(f"Databricks API {path} failed: {detail}") from exc
        except httpx.HTTPError as exc:
            logger.exception("databricks_api_transport_error", extra={"path": path})
            raise DatabricksError(f"Databricks API {path} failed: {exc}") from exc

        if not response.content:
            return {}
        return response.json()

    def get_run(self, run_id: str) -> dict:
        return self._request("GET", "/api/2.1/jobs/runs/get", params={"run_id": run_id})

    def export_run(
        self,
        run_id: str,
        views_to_export: Optional[List[str]] = None,
        *,
        timeout: float = 60.0,
    ) -> dict:
        params: Dict[str, Any] = {"run_id": run_id}
        if views_to_export:
            params["views_to_export"] = views_to_export
        return self._request(
            "GET",
            "/api/2.1/jobs/runs/export",
            params=params,
            timeout=timeout,
        )

    def get_failure_context(self, run_id: str) -> dict:
        export_data = self.export_run(run_id, views_to_export=["CODE", "RESULTS"])
        context = extract_failure_context(export_data)
        context["run_id"] = run_id
        return context

    def resolve_job_id(self, run_id: str, job_id: Optional[str] = None) -> Optional[str]:
        if job_id:
            return job_id
        run = self.get_run(run_id)
        resolved = run.get("job_id")
        return str(resolved) if resolved is not None else None
