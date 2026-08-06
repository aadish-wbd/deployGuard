"""Optional daily investigation cap (NFR-10 cost control)."""
import threading
from datetime import datetime, timezone
from typing import Optional


class DailyCap:
    def __init__(self, limit: Optional[int]):
        self._limit = limit
        self._lock = threading.Lock()
        self._day: Optional[str] = None
        self._count = 0

    def try_consume(self) -> bool:
        """Returns False if the daily cap has been reached."""
        if self._limit is None:
            return True

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._lock:
            if today != self._day:
                self._day = today
                self._count = 0
            if self._count >= self._limit:
                return False
            self._count += 1
            return True
