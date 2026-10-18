import os
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from redflag_backend.app import create_app
from redflag_backend.settings import Settings

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://redflag:redflag@localhost:5432/redflag"
)


def make_client(**overrides: object) -> TestClient:
    values: dict[str, object] = {
        "database_url": TEST_DB_URL,
        "frontend_origin": "http://localhost:3000",
    }
    values.update(overrides)
    return TestClient(create_app(Settings(**values)))  # type: ignore[arg-type]


def test_health_is_ok_when_database_works() -> None:
    response = make_client().get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_health_is_degraded_when_database_is_unreachable() -> None:
    dead_url = "postgresql+psycopg://redflag:redflag@localhost:1/redflag"

    response = make_client(database_url=dead_url, db_timeout_seconds=1).get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "error"


def test_health_reports_version_commit_and_fresh_timestamp() -> None:
    body = make_client(app_version="9.9.9", commit_sha="abc1234").get("/health").json()

    assert body["version"] == "9.9.9"
    assert body["commit"] == "abc1234"
    assert datetime.fromisoformat(body["timestamp"]).tzinfo is not None


def test_degraded_response_never_leaks_connection_details() -> None:
    dead_url = "postgresql+psycopg://secretuser:secretpass@db.internal.example:1/redflag"

    response = make_client(database_url=dead_url, db_timeout_seconds=1).get("/health")

    assert response.status_code == 503
    for leaked in ("secretuser", "secretpass", "db.internal.example", "Traceback"):
        assert leaked not in response.text


def test_cors_allows_only_the_configured_frontend_origin() -> None:
    client = make_client(frontend_origin="https://redflag.example")

    allowed = client.get("/health", headers={"Origin": "https://redflag.example"})
    other = client.get("/health", headers={"Origin": "https://evil.example"})

    assert allowed.headers.get("access-control-allow-origin") == "https://redflag.example"
    assert "access-control-allow-origin" not in other.headers


def test_startup_fails_fast_when_database_url_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:3000")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_database_url_from_neon_is_accepted_as_pasted() -> None:
    pasted = "postgresql://user:pw@ep-host.neon.tech/db?sslmode=require"

    settings = Settings(database_url=pasted, frontend_origin="http://localhost:3000")

    assert (
        settings.database_url == "postgresql+psycopg://user:pw@ep-host.neon.tech/db?sslmode=require"
    )
