"""Circuit breaker around generation (NFR-16, degraded mode).

The failure this prevents is the boring one: a provider starts timing out, every request
waits for the timeout, and a slow dependency becomes an outage. After `threshold`
consecutive failures the breaker opens and calls fail immediately, so the answer path can
degrade to retrieval-only instead of queueing.

States are the standard three - closed, open, half-open - and the clock is injectable, so
the cooldown is tested by moving time instead of sleeping for it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class CircuitOpen(Exception):
    """Raised instead of calling a dependency the breaker has given up on."""


class CircuitBreaker:
    """Counts consecutive failures; opens, then lets exactly one trial through."""

    def __init__(
        self,
        *,
        threshold: int = 2,
        cooldown_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = max(1, threshold)
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open = False

    @property
    def state(self) -> str:
        """closed / open / half_open, derived from counters and the clock."""
        if self._opened_at is None:
            return "half_open" if self._half_open else "closed"
        if self._clock() - self._opened_at >= self.cooldown_seconds:
            return "half_open"
        return "open"

    @property
    def failures(self) -> int:
        return self._failures

    def call(self, function: Callable[[], T]) -> T:
        """Run `function`, or raise CircuitOpen when the breaker is open."""
        state = self.state
        if state == "open":
            raise CircuitOpen("generation circuit is open")
        if state == "half_open":
            self._half_open = True
        try:
            result = function()
        except Exception:
            self._record_failure()
            raise
        self._record_success()
        return result

    def reset(self) -> None:
        """Operator escape hatch after a fix; also the test seam."""
        self._failures = 0
        self._opened_at = None
        self._half_open = False

    def _record_failure(self) -> None:
        self._failures += 1
        self._half_open = False
        if self._failures >= self.threshold:
            self._opened_at = self._clock()

    def _record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._half_open = False
