"""Saving setup drafts and versions. A draft is edited in place; a version never changes."""

import json
import secrets
import time
from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy import Engine, text

from redflag_backend.setups.models import SetupData

T = TypeVar("T")


class NoSuchSetup(Exception):
    pass


class NoSuchVersion(Exception):
    pass


class SetupStore:
    def __init__(self, engine: Engine, clock: Callable[[], float] = time.time) -> None:
        self._engine = engine
        self._clock = clock

    def create_draft(self) -> int:
        now = self._clock()
        with self._engine.begin() as conn:
            project_id = conn.execute(
                text(
                    "INSERT INTO projects (slug, name, description, created_at) "
                    "VALUES (:slug, 'Your bot', 'A bot tested from a setup the owner described', "
                    ":now) RETURNING id"
                ),
                {"slug": f"pending-{secrets.token_hex(6)}", "now": now},
            ).scalar_one()
            conn.execute(
                text("UPDATE projects SET slug = :slug WHERE id = :id"),
                {"slug": f"target-{project_id}", "id": project_id},
            )
            return int(
                conn.execute(
                    text(
                        "INSERT INTO setup_drafts (project_id, data, created_at, updated_at) "
                        "VALUES (:project_id, CAST(:data AS jsonb), :now, :now) RETURNING id"
                    ),
                    {
                        "project_id": project_id,
                        "data": SetupData().model_dump_json(),
                        "now": now,
                    },
                ).scalar_one()
            )

    def get_draft(self, setup_id: int) -> tuple[SetupData, str, int]:
        """The draft's data, its project slug and its project id."""
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT d.data, p.slug, p.id FROM setup_drafts d "
                    "JOIN projects p ON p.id = d.project_id WHERE d.id = :id"
                ),
                {"id": setup_id},
            ).first()
        if row is None:
            raise NoSuchSetup(setup_id)
        return SetupData.model_validate(row[0]), str(row[1]), int(row[2])

    def update_draft(self, setup_id: int, change: Callable[[SetupData], T]) -> T:
        """Apply a change to a draft in one transaction, so two edits cannot clash."""
        with self._engine.begin() as conn:
            row = conn.execute(
                text("SELECT data FROM setup_drafts WHERE id = :id FOR UPDATE"), {"id": setup_id}
            ).first()
            if row is None:
                raise NoSuchSetup(setup_id)
            data = SetupData.model_validate(row[0])
            result = change(data)
            conn.execute(
                text(
                    "UPDATE setup_drafts SET data = CAST(:data AS jsonb), updated_at = :now "
                    "WHERE id = :id"
                ),
                {"data": data.model_dump_json(), "now": self._clock(), "id": setup_id},
            )
        return result

    def confirm(self, setup_id: int) -> int:
        """Save a numbered copy of the draft. The copy holds the fields and the endpoint settings
        (never the key) and is never changed afterwards."""
        with self._engine.begin() as conn:
            row = conn.execute(
                text("SELECT data, project_id FROM setup_drafts WHERE id = :id FOR UPDATE"),
                {"id": setup_id},
            ).first()
            if row is None:
                raise NoSuchSetup(setup_id)
            data = SetupData.model_validate(row[0])
            number = conn.execute(
                text(
                    "SELECT COALESCE(MAX(number), 0) + 1 FROM setup_versions WHERE project_id = :p"
                ),
                {"p": row[1]},
            ).scalar_one()
            snapshot = {
                "fields": data.fields.model_dump(),
                "endpoint": data.endpoint.model_dump(),
            }
            conn.execute(
                text(
                    "INSERT INTO setup_versions (project_id, number, data, created_at) "
                    "VALUES (:p, :n, CAST(:data AS jsonb), :now)"
                ),
                {"p": row[1], "n": number, "data": json.dumps(snapshot), "now": self._clock()},
            )
        return int(number)

    def list_versions(self, setup_id: int) -> list[dict[str, Any]]:
        _, _, project_id = self.get_draft(setup_id)
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT number, created_at FROM setup_versions WHERE project_id = :p "
                    "ORDER BY number"
                ),
                {"p": project_id},
            ).all()
        return [{"number": int(r[0]), "created_at": float(r[1])} for r in rows]

    def get_version(self, setup_id: int, number: int) -> dict[str, Any]:
        _, _, project_id = self.get_draft(setup_id)
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT data, created_at FROM setup_versions "
                    "WHERE project_id = :p AND number = :n"
                ),
                {"p": project_id, "n": number},
            ).first()
        if row is None:
            raise NoSuchVersion(number)
        return {"number": number, "created_at": float(row[1]), **row[0]}
