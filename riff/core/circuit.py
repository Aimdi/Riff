"""Simple circuit breaker for fragile upstream APIs."""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from typing import TypeVar

from .errors import RiffCircuitOpen

log = logging.getLogger("riff.circuit")

T = TypeVar("T")


class CircuitBreaker:
    """Open after *threshold* consecutive failures; half-open after *reset_after*."""

    def __init__(
        self,
        *,
        name: str = "api",
        threshold: int = 5,
        reset_after: float = 60.0,
    ):
        self.name = name
        self.threshold = threshold
        self.reset_after = reset_after
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            if time.monotonic() - self._opened_at >= self.reset_after:
                return False  # half-open: allow a trial
            return True

    @property
    def consecutive_failures(self) -> int:
        with self._lock:
            return self._failures

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.threshold and self._opened_at is None:
                self._opened_at = time.monotonic()
                log.warning(
                    "circuit %s OPEN after %d failures",
                    self.name,
                    self._failures,
                )

    def before_call(self) -> None:
        if self.is_open:
            raise RiffCircuitOpen(
                f"YouTube Music API circuit open ({self.name}) — "
                "try again in a minute, or run riff-update if this persists"
            )

    def call(self, fn: Callable[[], T]) -> T:
        self.before_call()
        try:
            result = fn()
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.4,
    max_delay: float = 4.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    label: str = "op",
) -> T:
    """Run *fn* with exponential backoff + jitter on transient errors."""
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return fn()
        except retry_on as exc:
            last = exc
            if i + 1 >= attempts:
                break
            delay = min(max_delay, base_delay * (2**i))
            delay *= 0.5 + random.random()  # jitter
            log.debug("%s attempt %d failed (%s); retry in %.2fs", label, i + 1, exc, delay)
            time.sleep(delay)
    assert last is not None
    raise last
