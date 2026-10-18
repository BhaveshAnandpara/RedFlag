"""Saved answers, kept in Postgres so they survive a restart.

Only temperature-0 requests are saved (a random answer would be wrong to reuse). The key is
the content of the request, not the provider, so any provider's answer can be reused; the
entry remembers which provider and model produced it. Entries expire, and the table has a
hard size cap so it cannot crowd out Neon's 0.5 GB free plan.
"""

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import Engine, text

from redflag_backend.llm.types import LLMAnswer, LLMRequest


@dataclass(frozen=True)
class CachedAnswer:
    provider: str
    answer: LLMAnswer


def cache_key(request: LLMRequest) -> str:
    canonical = json.dumps(
        {
            "messages": [[m.role, m.content] for m in request.messages],
            "temperature": request.temperature,
            "max_output_tokens": request.max_output_tokens,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class SqlCache:
    def __init__(self, engine: Engine, ttl_seconds: float, max_bytes: int) -> None:
        self._engine = engine
        self._ttl = ttl_seconds
        self._max_bytes = max_bytes

    def get(self, key: str, now: float) -> CachedAnswer | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT provider, model, answer, input_tokens, output_tokens "
                    "FROM llm_cache WHERE key = :key AND expires_at > :now"
                ),
                {"key": key, "now": now},
            ).one_or_none()
        if row is None:
            return None
        provider, model, answer, input_tokens, output_tokens = row
        return CachedAnswer(provider, LLMAnswer(answer, model, input_tokens, output_tokens))

    def put(self, key: str, provider: str, answer: LLMAnswer, now: float) -> None:
        size = len(key) + len(answer.text.encode()) + len(answer.model) + len(provider)
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO llm_cache (key, provider, model, answer, input_tokens, "
                    "output_tokens, created_at, expires_at, size_bytes) VALUES (:key, "
                    ":provider, :model, :answer, :input_tokens, :output_tokens, :now, "
                    ":expires_at, :size) ON CONFLICT (key) DO UPDATE SET provider = "
                    "EXCLUDED.provider, model = EXCLUDED.model, answer = EXCLUDED.answer, "
                    "input_tokens = EXCLUDED.input_tokens, output_tokens = "
                    "EXCLUDED.output_tokens, created_at = EXCLUDED.created_at, expires_at = "
                    "EXCLUDED.expires_at, size_bytes = EXCLUDED.size_bytes"
                ),
                {
                    "key": key,
                    "provider": provider,
                    "model": answer.model,
                    "answer": answer.text,
                    "input_tokens": answer.input_tokens,
                    "output_tokens": answer.output_tokens,
                    "now": now,
                    "expires_at": now + self._ttl,
                    "size": size,
                },
            )
            conn.execute(text("DELETE FROM llm_cache WHERE expires_at <= :now"), {"now": now})
            # Over the cap: drop the oldest entries first until the total fits.
            conn.execute(
                text(
                    "DELETE FROM llm_cache WHERE key IN ("
                    "SELECT key FROM ("
                    "SELECT key, SUM(size_bytes) OVER (ORDER BY created_at DESC, key) AS running "
                    "FROM llm_cache) ranked WHERE running > :cap)"
                ),
                {"cap": self._max_bytes},
            )

    def clear(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(text("DELETE FROM llm_cache"))
