"""Stable fingerprint for duplicate error investigations."""
from __future__ import annotations

import hashlib


def investigation_fingerprint(error_message: str, service: str, environment: str) -> str:
    """SHA-256 hex digest of error_message + service + environment."""
    raw = f"{error_message}|{service}|{environment}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def investigation_fingerprint_label(error_message: str, service: str, environment: str) -> str:
    """JIRA-safe label tying a ticket to a specific error fingerprint."""
    return f"dgfp{investigation_fingerprint(error_message, service, environment)[:12]}"
