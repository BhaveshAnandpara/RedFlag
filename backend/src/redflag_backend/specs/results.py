"""Saving results: the proof for each finished test, kept only if it keeps the contract.

A result is refused, with the reasons in plain words, when it breaks a trust rule (see
`contract.py`). Any API key the caller knows about is swapped for `$YOUR_KEY` before saving, so a
saved result, its JSON and its curl never hold a real key.
"""

import json
import shlex
import time
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine, text

from redflag_backend.specs.contract import Compared, ResultRecord, problems
from redflag_backend.specs.store import SpecStore, StoredSpec

KEY_PLACEHOLDER = "$YOUR_KEY"
COLUMNS = "run_id, spec_id, spec_version, spec_hash, record, created_at"


class InvalidResult(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class StoredResult(BaseModel):
    run_id: str
    spec_version: int
    created_at: float
    result: ResultRecord

    @property
    def replay(self) -> list[str]:
        """What to resend to run this attack again: the attacker's own messages, in order."""
        return list(self.result.attacker_messages)


def scrub(record: ResultRecord, secrets: Sequence[str]) -> ResultRecord:
    """Swap every known secret for the placeholder, wherever it appears in the record."""
    as_text = record.model_dump_json()
    for secret in {s for s in secrets if s}:
        as_text = as_text.replace(json.dumps(secret)[1:-1], KEY_PLACEHOLDER)
    return ResultRecord.model_validate_json(as_text)


def _compare(previous: str | None, now: str) -> Compared:
    if previous is None:
        return "first_run"
    if previous == "broke":
        return "still_broken" if now == "broke" else "fixed"
    return "new"


def _stored(row: Any) -> StoredResult:
    return StoredResult(
        run_id=row.run_id,
        spec_version=row.spec_version,
        created_at=row.created_at,
        result=ResultRecord.model_validate(row.record),
    )


class ResultStore:
    def __init__(
        self, engine: Engine, specs: SpecStore, clock: Callable[[], float] = time.time
    ) -> None:
        self._engine = engine
        self._specs = specs
        self._clock = clock

    def save(self, run_id: str, record: ResultRecord, secrets: Sequence[str] = ()) -> StoredResult:
        record = scrub(record, secrets)
        spec = self._spec_for(record)
        reasons = problems(record, spec)
        if reasons:
            raise InvalidResult(reasons)
        with self._engine.begin() as conn:
            previous = conn.execute(
                text(
                    "SELECT outcome FROM test_results WHERE spec_id = :id AND run_id <> :run "
                    "ORDER BY created_at DESC, id DESC LIMIT 1"
                ),
                {"id": record.spec_id, "run": run_id},
            ).scalar()
            if record.compared_with_last is None:
                record = record.model_copy(
                    update={"compared_with_last": _compare(previous, record.outcome)}
                )
            row = conn.execute(
                text(
                    "INSERT INTO test_results "
                    "(run_id, spec_id, spec_version, spec_hash, outcome, record, created_at) "
                    "VALUES (:run, :id, :v, :hash, :outcome, CAST(:record AS jsonb), :now) "
                    f"RETURNING {COLUMNS}"
                ),
                {
                    "run": run_id,
                    "id": record.spec_id,
                    "v": spec.version,
                    "hash": record.spec_hash,
                    "outcome": record.outcome,
                    "record": record.model_dump_json(),
                    "now": self._clock(),
                },
            ).one()
        return _stored(row)

    def for_run(self, run_id: str) -> list[StoredResult]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT {COLUMNS} FROM test_results WHERE run_id = :run ORDER BY id"),
                {"run": run_id},
            ).all()
        return [_stored(r) for r in rows]

    def _spec_for(self, record: ResultRecord) -> StoredSpec:
        """The saved version the result names. A hash that matches no version is checked against
        the latest, so the 'does not point at this spec' reason is the one the caller sees."""
        history = self._specs.history(record.spec_id)
        for version in history:
            if version.hash == record.spec_hash:
                return version
        return history[-1]


def as_json(result: StoredResult) -> str:
    return json.dumps(result.result.model_dump(mode="json"), indent=2)


def as_curl(result: StoredResult, url: str, body_field: str = "message") -> str:
    """One curl per attacker message, with the key as a placeholder, never the real one. A bot
    that keeps a conversation needs them sent in order."""
    commands = []
    for message in result.replay:
        body = json.dumps({body_field: message})
        commands.append(
            f"curl -X POST {shlex.quote(url)} "
            f'-H "Authorization: Bearer {KEY_PLACEHOLDER}" '
            f"-H 'Content-Type: application/json' -d {shlex.quote(body)}"
        )
    return "\n".join(commands)
