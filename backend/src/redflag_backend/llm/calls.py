"""The attempt log: one row per provider attempt, so every switch is on record (NFR-06).

Prompts and answers are not stored here, only who was asked, what happened and how much it
used. The table is trimmed to a fixed number of rows so it cannot grow without bound.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Engine, text

from redflag_backend.llm.router import Attempt


class CallLog:
    def __init__(self, engine: Engine, max_rows: int) -> None:
        self._engine = engine
        self._max_rows = max_rows

    def record(
        self,
        session_id: str,
        attempts: Sequence[Attempt],
        usage: tuple[int, int] | None,
        cached: bool,
        paid: bool,
        now: float,
    ) -> None:
        if not attempts:
            return
        rows = [
            {
                "created_at": now,
                "session_id": session_id,
                "provider": a.provider,
                "model": a.model,
                "outcome": a.outcome,
                "latency_ms": a.latency_ms,
                "input_tokens": usage[0] if usage and a.outcome == "ok" else None,
                "output_tokens": usage[1] if usage and a.outcome == "ok" else None,
                "cached": cached,
                "paid": paid and a.outcome == "ok",
            }
            for a in attempts
        ]
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO llm_calls (created_at, session_id, provider, model, outcome, "
                    "latency_ms, input_tokens, output_tokens, cached, paid) VALUES "
                    "(:created_at, :session_id, :provider, :model, :outcome, :latency_ms, "
                    ":input_tokens, :output_tokens, :cached, :paid)"
                ),
                rows,
            )
            conn.execute(
                text(
                    "DELETE FROM llm_calls WHERE id NOT IN "
                    "(SELECT id FROM llm_calls ORDER BY id DESC LIMIT :keep)"
                ),
                {"keep": self._max_rows},
            )

    def recent(self, limit: int) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT created_at, session_id, provider, model, outcome, latency_ms, "
                    "input_tokens, output_tokens, cached, paid FROM llm_calls "
                    "ORDER BY id DESC LIMIT :limit"
                ),
                {"limit": limit},
            )
            return [dict(row._mapping) for row in result]
