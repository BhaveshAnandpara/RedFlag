"""Per-session limits, so a scan can never run away with requests, text, time or parallel calls.

Sessions live in memory: a restart clears them, and a scan that straddles a restart is stopped
rather than continued with wrong numbers. Caps are fixed when a session first appears.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class BudgetCaps:
    requests: int
    tokens: int
    seconds: float
    concurrency: int


class SessionBudget:
    def __init__(self, caps: BudgetCaps, started: float) -> None:
        self.caps = caps
        self.started = started
        self.requests_used = 0
        self.tokens_used = 0
        # Calls beyond the concurrency cap wait their turn rather than fail.
        self.slots = asyncio.Semaphore(caps.concurrency)

    def exceeded(self, now: float) -> str | None:
        """Name of the first cap that has been reached, or None while there is room."""
        if self.requests_used >= self.caps.requests:
            return "requests"
        if self.tokens_used >= self.caps.tokens:
            return "tokens"
        if now - self.started >= self.caps.seconds:
            return "seconds"
        return None

    def snapshot(self, now: float) -> dict[str, Any]:
        return {
            "requests": {"used": self.requests_used, "limit": self.caps.requests},
            "tokens": {"used": self.tokens_used, "limit": self.caps.tokens},
            "seconds": {"used": round(now - self.started, 1), "limit": self.caps.seconds},
            "concurrency": {"limit": self.caps.concurrency},
        }


class BudgetBook:
    def __init__(
        self, defaults: BudgetCaps, clock: Callable[[], float], max_sessions: int = 1000
    ) -> None:
        self._defaults = defaults
        self._clock = clock
        self._max_sessions = max_sessions
        self._sessions: dict[str, SessionBudget] = {}

    def session(self, session_id: str, overrides: dict[str, float | int] | None) -> SessionBudget:
        existing = self._sessions.get(session_id)
        if existing is not None:
            return existing
        caps = self._defaults
        if overrides:
            caps = replace(caps, **overrides)  # type: ignore[arg-type]
        if len(self._sessions) >= self._max_sessions:
            # Forget the oldest session so memory cannot grow without bound.
            self._sessions.pop(next(iter(self._sessions)))
        budget = SessionBudget(caps, started=self._clock())
        self._sessions[session_id] = budget
        return budget
