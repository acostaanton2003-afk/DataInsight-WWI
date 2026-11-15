"""Bounded per-process limiter for authenticated assistant requests."""
from threading import Lock
from time import monotonic
from uuid import UUID


class AssistantRateLimiter:
    def __init__(self, limit: int = 6, window: int = 60, capacity: int = 2048) -> None:
        self.limit = limit
        self.window = window
        self.capacity = capacity
        self._buckets: dict[UUID, tuple[float, int]] = {}
        self._lock = Lock()

    def allow(self, user_id: UUID) -> bool:
        now = monotonic()
        with self._lock:
            self._buckets = {key: value for key, value in self._buckets.items()
                             if now - value[0] < self.window}
            start, count = self._buckets.get(user_id, (now, 0))
            if count >= self.limit or (user_id not in self._buckets and len(self._buckets) >= self.capacity):
                return False
            self._buckets[user_id] = (start, count + 1)
            return True
