"""Thread-safe rate (FPS) and latency meters."""
from __future__ import annotations

import threading
import time
from collections import deque


class RateMeter:
    """Events per second over a sliding time window."""

    def __init__(self, window_s: float = 2.0):
        self.window_s = window_s
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def tick(self, t: float | None = None) -> None:
        t = time.monotonic() if t is None else t
        with self._lock:
            self._times.append(t)
            self._prune(t)

    def rate(self, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._prune(now)
            return len(self._times) / self.window_s

    def _prune(self, now: float) -> None:
        while self._times and now - self._times[0] > self.window_s:
            self._times.popleft()


class LatencyMeter:
    """Rolling mean of the most recent latency samples, in milliseconds."""

    def __init__(self, size: int = 30):
        self._samples: deque[float] = deque(maxlen=size)
        self._lock = threading.Lock()

    def add(self, seconds: float) -> None:
        with self._lock:
            self._samples.append(seconds)

    def mean_ms(self) -> float | None:
        with self._lock:
            if not self._samples:
                return None
            return 1000.0 * sum(self._samples) / len(self._samples)
