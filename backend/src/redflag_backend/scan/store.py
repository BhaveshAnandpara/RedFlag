"""Saving scans: projects, the scan itself, and one result row per test."""

import json
from typing import Any

from sqlalchemy import Engine, text

RESULT_COLUMNS = (
    "position, test_id, risk, kind, title, message, status, reply, tool_calls, evidence, rule, "
    "model, provider, attempts, started_at, finished_at, severity, remediation, rule_status, "
    "rule_evidence, judge_status, judge_reason, judge_model, judge_provider, turns"
)


class ScanStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def ensure_project(self, slug: str, name: str, description: str) -> int:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO projects (slug, name, description, created_at) "
                    "VALUES (:slug, :name, :description, extract(epoch from now())) "
                    "ON CONFLICT (slug) DO UPDATE SET name = :name, description = :description "
                    "RETURNING id"
                ),
                {"slug": slug, "name": name, "description": description},
            ).one()
        return int(row[0])

    def create_scan(
        self,
        project_id: int,
        settings: dict[str, Any],
        now: float,
        setup_version_id: int | None = None,
    ) -> int:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO scans (project_id, status, settings, started_at, "
                    "last_progress_at, setup_version_id) "
                    "VALUES (:project_id, 'running', CAST(:settings AS jsonb), :now, :now, "
                    ":version_id) RETURNING id"
                ),
                {
                    "project_id": project_id,
                    "settings": json.dumps(settings),
                    "now": now,
                    "version_id": setup_version_id,
                },
            ).one()
        return int(row[0])

    def add_result(self, scan_id: int, result: dict[str, Any], now: float) -> None:
        values = {
            "severity": None,
            "remediation": None,
            "rule_status": None,
            "rule_evidence": None,
            "judge_status": None,
            "judge_reason": None,
            "judge_model": None,
            "judge_provider": None,
            **result,
            "scan_id": scan_id,
            "tool_calls": json.dumps(result["tool_calls"]),
            "attempts": json.dumps(result["attempts"]),
            "turns": json.dumps(result["turns"]) if result.get("turns") is not None else None,
        }
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO scan_results (scan_id, position, test_id, risk, kind, title, "
                    "message, status, reply, tool_calls, evidence, rule, model, provider, "
                    "attempts, started_at, finished_at, severity, remediation, rule_status, "
                    "rule_evidence, judge_status, judge_reason, judge_model, judge_provider, "
                    "turns) "
                    "VALUES (:scan_id, :position, :test_id, "
                    ":risk, :kind, :title, :message, :status, :reply, CAST(:tool_calls AS jsonb), "
                    ":evidence, :rule, :model, :provider, CAST(:attempts AS jsonb), :started_at, "
                    ":finished_at, :severity, :remediation, :rule_status, :rule_evidence, "
                    ":judge_status, :judge_reason, :judge_model, :judge_provider, "
                    "CAST(:turns AS jsonb))"
                ),
                values,
            )
            conn.execute(
                text("UPDATE scans SET last_progress_at = :now WHERE id = :id"),
                {"now": now, "id": scan_id},
            )

    def finish_scan(self, scan_id: int, status: str, now: float, note: str | None = None) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE scans SET status = :status, finished_at = :now, note = :note "
                    "WHERE id = :id AND status = 'running'"
                ),
                {"status": status, "now": now, "note": note, "id": scan_id},
            )

    def interrupt_stale(self, now: float, stale_after: float) -> int:
        """Mark running scans with no recent progress as interrupted. Returns how many."""
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "UPDATE scans SET status = 'interrupted', finished_at = :now, "
                    "note = 'No progress for a while: the backend probably restarted or went "
                    "to sleep. Run the scan again.' "
                    "WHERE status = 'running' AND last_progress_at < :cutoff"
                ),
                {"now": now, "cutoff": now - stale_after},
            )
        return result.rowcount

    def get_scan(self, scan_id: int) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            scan = (
                conn.execute(
                    text(
                        "SELECT s.id, p.slug AS bot_id, s.status, s.note, s.settings, "
                        "s.started_at, "
                        "s.finished_at, s.last_progress_at FROM scans s "
                        "JOIN projects p ON p.id = s.project_id WHERE s.id = :id"
                    ),
                    {"id": scan_id},
                )
                .mappings()
                .first()
            )
            if scan is None:
                return None
            results = (
                conn.execute(
                    text(
                        f"SELECT {RESULT_COLUMNS} FROM scan_results WHERE scan_id = :id "
                        "ORDER BY position"
                    ),
                    {"id": scan_id},
                )
                .mappings()
                .all()
            )
        return {"scan": dict(scan), "results": [dict(r) for r in results]}

    def previous_scan_id(self, scan_id: int) -> int | None:
        """The latest completed scan of the same project before this one, if there is one."""
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT p.id FROM scans p JOIN scans s ON s.project_id = p.project_id "
                    "WHERE s.id = :id AND p.id < s.id AND p.status = 'completed' "
                    "ORDER BY p.id DESC LIMIT 1"
                ),
                {"id": scan_id},
            ).first()
        return int(row[0]) if row else None

    def list_scans(self, bot_id: str | None, limit: int) -> list[dict[str, Any]]:
        """Newest first, each with how many results ended each way."""
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT s.id, p.slug AS bot_id, s.status, s.started_at, s.finished_at, "
                        "COALESCE(jsonb_object_agg(r.status, r.n) "
                        "FILTER (WHERE r.status IS NOT NULL), "
                        "'{}'::jsonb) AS counts FROM scans s "
                        "JOIN projects p ON p.id = s.project_id "
                        "LEFT JOIN (SELECT scan_id, status, count(*) AS n FROM scan_results "
                        "GROUP BY scan_id, status) r ON r.scan_id = s.id "
                        "WHERE (CAST(:bot_id AS text) IS NULL OR p.slug = :bot_id) "
                        "GROUP BY s.id, p.slug ORDER BY s.id DESC LIMIT :limit"
                    ),
                    {"bot_id": bot_id, "limit": limit},
                )
                .mappings()
                .all()
            )
        return [dict(r) for r in rows]

    # --- judge labels ------------------------------------------------------------------------

    def has_result(self, scan_id: int, test_id: str) -> bool:
        with self._engine.connect() as conn:
            found = conn.execute(
                text("SELECT 1 FROM scan_results WHERE scan_id = :s AND test_id = :t"),
                {"s": scan_id, "t": test_id},
            ).first()
        return found is not None

    def set_label(self, scan_id: int, test_id: str, correct: str, now: float) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO judge_labels (scan_id, test_id, correct, labeled_at) "
                    "VALUES (:s, :t, :c, :now) ON CONFLICT (scan_id, test_id) "
                    "DO UPDATE SET correct = :c, labeled_at = :now"
                ),
                {"s": scan_id, "t": test_id, "c": correct, "now": now},
            )

    def clear_label(self, scan_id: int, test_id: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM judge_labels WHERE scan_id = :s AND test_id = :t"),
                {"s": scan_id, "t": test_id},
            )

    def labels(self, scan_id: int) -> dict[str, str]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT test_id, correct FROM judge_labels WHERE scan_id = :s"),
                {"s": scan_id},
            ).all()
        return {str(r[0]): str(r[1]) for r in rows}

    def labeled_results(self) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT r.risk, r.judge_status, l.correct FROM judge_labels l "
                        "JOIN scan_results r ON r.scan_id = l.scan_id AND r.test_id = l.test_id"
                    )
                )
                .mappings()
                .all()
            )
        return [dict(r) for r in rows]
