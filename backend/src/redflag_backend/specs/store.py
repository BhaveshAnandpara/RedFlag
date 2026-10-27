"""Saving specs. A draft spec is edited in place; once locked it never changes.

Locking happens when the user approves the plan. After that, changing a spec makes a new version
with a new hash and leaves the old one as it was, so a past result can always say exactly what was
promised. Saving the same content again makes no new version.
"""

import secrets
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine, text

from redflag_backend.specs.spec import TestSpec, spec_hash


class NoSuchSpec(Exception):
    pass


class StoredSpec(BaseModel):
    spec_id: str
    version: int
    hash: str
    spec: TestSpec
    locked: bool
    created_at: float
    locked_at: float | None = None


def _stored(row: Any) -> StoredSpec:
    return StoredSpec(
        spec_id=row.spec_id,
        version=row.version,
        hash=row.spec_hash,
        spec=TestSpec.model_validate(row.spec),
        locked=row.locked_at is not None,
        created_at=row.created_at,
        locked_at=row.locked_at,
    )


COLUMNS = "spec_id, version, spec_hash, spec, created_at, locked_at"


class SpecStore:
    def __init__(self, engine: Engine, clock: Callable[[], float] = time.time) -> None:
        self._engine = engine
        self._clock = clock

    def create(self, spec: TestSpec) -> StoredSpec:
        spec_id = f"spec-{secrets.token_hex(6)}"
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO test_specs (spec_id, version, spec_hash, spec, created_at) "
                    "VALUES (:id, 1, :hash, CAST(:spec AS jsonb), :now) "
                    f"RETURNING {COLUMNS}"
                ),
                {
                    "id": spec_id,
                    "hash": spec_hash(spec),
                    "spec": spec.model_dump_json(),
                    "now": self._clock(),
                },
            ).one()
        return _stored(row)

    def get(self, spec_id: str, version: int | None = None) -> StoredSpec:
        with self._engine.connect() as conn:
            if version is None:
                query = (
                    f"SELECT {COLUMNS} FROM test_specs WHERE spec_id = :id "
                    "ORDER BY version DESC LIMIT 1"
                )
                row = conn.execute(text(query), {"id": spec_id}).one_or_none()
            else:
                query = f"SELECT {COLUMNS} FROM test_specs WHERE spec_id = :id AND version = :v"
                row = conn.execute(text(query), {"id": spec_id, "v": version}).one_or_none()
        if row is None:
            raise NoSuchSpec(spec_id)
        return _stored(row)

    def history(self, spec_id: str) -> list[StoredSpec]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT {COLUMNS} FROM test_specs WHERE spec_id = :id ORDER BY version"),
                {"id": spec_id},
            ).all()
        if not rows:
            raise NoSuchSpec(spec_id)
        return [_stored(r) for r in rows]

    def edit(self, spec_id: str, spec: TestSpec) -> StoredSpec:
        """Change a spec. A draft is edited in place. A locked spec is left as it was and the
        change becomes the next version, unless nothing changed."""
        new_hash = spec_hash(spec)
        with self._engine.begin() as conn:
            latest = conn.execute(
                text(
                    f"SELECT {COLUMNS} FROM test_specs WHERE spec_id = :id "
                    "ORDER BY version DESC LIMIT 1 FOR UPDATE"
                ),
                {"id": spec_id},
            ).one_or_none()
            if latest is None:
                raise NoSuchSpec(spec_id)
            if latest.spec_hash == new_hash:
                return _stored(latest)
            params = {"id": spec_id, "hash": new_hash, "spec": spec.model_dump_json()}
            if latest.locked_at is None:
                row = conn.execute(
                    text(
                        "UPDATE test_specs SET spec_hash = :hash, spec = CAST(:spec AS jsonb) "
                        f"WHERE spec_id = :id AND version = :v RETURNING {COLUMNS}"
                    ),
                    {**params, "v": latest.version},
                ).one()
            else:
                row = conn.execute(
                    text(
                        "INSERT INTO test_specs (spec_id, version, spec_hash, spec, created_at) "
                        "VALUES (:id, :v, :hash, CAST(:spec AS jsonb), :now) "
                        f"RETURNING {COLUMNS}"
                    ),
                    {**params, "v": latest.version + 1, "now": self._clock()},
                ).one()
        return _stored(row)

    def lock(self, spec_id: str) -> StoredSpec:
        """Lock the latest version, as when the user approves the plan. Locking twice is fine."""
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "UPDATE test_specs SET locked_at = COALESCE(locked_at, :now) "
                    "WHERE spec_id = :id AND version = ("
                    "SELECT MAX(version) FROM test_specs WHERE spec_id = :id) "
                    f"RETURNING {COLUMNS}"
                ),
                {"id": spec_id, "now": self._clock()},
            ).one_or_none()
        if row is None:
            raise NoSuchSpec(spec_id)
        return _stored(row)

    def lock_many(self, spec_ids: list[str]) -> list[StoredSpec]:
        return [self.lock(spec_id) for spec_id in spec_ids]
