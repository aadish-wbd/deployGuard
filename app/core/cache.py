"""Dedup cache for identical investigations (NFR-5).

Hashes (error_message + service + deploy_sha) and returns a cached result
if the same investigation was completed within the TTL window. In-memory
and per-process only — fine for a single-instance hackathon deployment;
a multi-instance deployment would need a shared store (DynamoDB/Redis).
"""
import hashlib
import threading
import time
from typing import Any, Optional


class TTLCache:
    def __init__(self, ttl_seconds: int):
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def make_key(error_message: str, service: str, deploy_sha: Optional[str]) -> str:
        raw = f"{error_message}|{service}|{deploy_sha or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

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
