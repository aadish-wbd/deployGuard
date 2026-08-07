"""Dedup cache for identical investigations (NFR-5).

Hashes (error_message + service + environment) and returns a cached result if the same
investigation was completed within the TTL window. In-memory and per-process
only — fine for a single-instance hackathon deployment; a multi-instance
deployment would need a shared store (DynamoDB/Redis).
"""
import threading
import time
from typing import Any, Optional


class TTLCache:
    def __init__(self, ttl_seconds: int):
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def make_key(error_message: str, service: str, environment: str) -> str:
        from app.core.investigation_fingerprint import investigation_fingerprint

        return investigation_fingerprint(error_message, service, environment)

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + self._ttl, value)
