"""Stable fingerprint for duplicate error investigations."""
from __future__ import annotations

from typing import Optional

from app.core.cache import TTLCache


def investigation_fingerprint(error_message: str, service: str, deploy_sha: Optional[str]) -> str:
    """SHA-256 hex digest of error_message + service + deploy_sha."""
    return TTLCache.make_key(error_message, service, deploy_sha)


def investigation_fingerprint_label(error_message: str, service: str, deploy_sha: Optional[str]) -> str:
    """JIRA-safe label tying a ticket to a specific error fingerprint."""
    return f"dgfp{investigation_fingerprint(error_message, service, deploy_sha)[:12]}"
