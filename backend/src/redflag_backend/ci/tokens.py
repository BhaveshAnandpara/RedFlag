"""API tokens for CI. A token is shown once and only its hash is stored."""

import hashlib
import secrets
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import Engine, text

PREFIX = "rf_"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class CiTokenStore:
    def __init__(self, engine: Engine, clock: Callable[[], float] = time.time) -> None:
        self._engine = engine
        self._clock = clock

    def create(self, setup_id: int, label: str) -> tuple[int, str]:
        token = PREFIX + secrets.token_urlsafe(32)
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO ci_tokens (setup_id, label, token_hash, created_at) "
                    "VALUES (:setup, :label, :hash, :now) RETURNING id"
                ),
                {
                    "setup": setup_id,
                    "label": label,
                    "hash": hash_token(token),
                    "now": self._clock(),
                },
            ).one()
        return int(row[0]), token

    def list(self, setup_id: int) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, label, created_at, last_used_at, revoked FROM ci_tokens "
                    "WHERE setup_id = :setup ORDER BY id"
                ),
                {"setup": setup_id},
            ).all()
        return [
            {
                "id": int(r[0]),
                "label": str(r[1]),
                "created_at": float(r[2]),
                "last_used_at": float(r[3]) if r[3] is not None else None,
                "revoked": bool(r[4]),
            }
            for r in rows
        ]

    def revoke(self, setup_id: int, token_id: int) -> bool:
        with self._engine.begin() as conn:
            result = conn.execute(
                text("UPDATE ci_tokens SET revoked = true WHERE id = :id AND setup_id = :setup"),
                {"id": token_id, "setup": setup_id},
            )
        return result.rowcount > 0

    def authenticate(self, token: str) -> int | None:
        """The setup a live token belongs to, or None. Records that the token was used."""
        if not token.startswith(PREFIX):
            return None
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "UPDATE ci_tokens SET last_used_at = :now "
                    "WHERE token_hash = :hash AND NOT revoked RETURNING setup_id"
                ),
                {"hash": hash_token(token), "now": self._clock()},
            ).first()
        return int(row[0]) if row else None
