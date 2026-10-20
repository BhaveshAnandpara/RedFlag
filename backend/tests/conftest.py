"""Test database setup: migrate once per run, and start each test with empty tables."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from tests.helpers import TEST_DB_URL

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    """Apply every migration to the test database, exactly as a deploy would."""
    previous = {k: os.environ.get(k) for k in ("DATABASE_URL", "DATABASE_URL_UNPOOLED")}
    os.environ["DATABASE_URL"] = TEST_DB_URL
    os.environ.pop("DATABASE_URL_UNPOOLED", None)
    try:
        command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture(autouse=True)
def empty_router_tables(migrated_database: None) -> None:
    engine = create_engine(TEST_DB_URL)
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE llm_cache, llm_calls, llm_spend, judge_labels, scan_results, scans, "
                "generated_tests, "
                "ci_tokens, setup_versions, setup_drafts, projects "
                "RESTART IDENTITY CASCADE"
            )
        )
    engine.dispose()
