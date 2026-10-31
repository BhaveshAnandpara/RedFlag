"""The developer switch: ENV=dev lets Redflag call a bot on the developer's own machine.

It must be off unless ENV is exactly "dev", and off on a hosted server whatever ENV says.
"""

import json
import logging
from typing import Any

import pytest

from redflag_backend.settings import Settings
from tests.helpers import OWNER, TEST_DB_URL
from tests.test_quick_scan import ENDPOINT
from tests.test_setup_runs import run_client

LOCAL = {**ENDPOINT, "url": "http://127.0.0.1:3000/api/chat/completions"}


def settings(**changes: Any) -> Settings:
    return Settings(database_url=TEST_DB_URL, frontend_origin="http://localhost:3001", **changes)


@pytest.fixture(autouse=True)
def not_on_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RENDER", raising=False)
    # Not removed but set: a developer's own .env may say ENV=dev, and a test that asks for the
    # default must get production, not that.
    monkeypatch.setenv("ENV", "prod")


def test_it_is_off_unless_env_says_dev() -> None:
    assert settings().env == "prod" and settings().allow_private_targets is False
    for value in ("prod", "production", "development", "staging", "", "devv", "no"):
        assert settings(env=value).allow_private_targets is False, value
    for value in ("dev", "DEV", " dev "):
        assert settings(env=value).allow_private_targets is True, value


def test_it_reads_the_env_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "dev")
    assert settings().allow_private_targets is True
    monkeypatch.setenv("ENV", "prod")
    assert settings().allow_private_targets is False


def test_a_hosted_server_never_allows_it_even_if_env_says_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RENDER", "true")
    assert settings(env="dev").allow_private_targets is False


def check(client: Any, endpoint: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = client.post(
        "/quick-scans/check", json={"endpoint": endpoint, "key": "k"}, headers=OWNER
    ).json()
    return body


def test_by_default_the_hello_check_refuses_a_local_bot_and_sends_nothing() -> None:
    with run_client() as (client, _, endpoint):
        body = check(client, LOCAL)
        assert body["status"] == "error" and "private or internal" in body["error"]
        assert endpoint.requests == []


def test_with_env_dev_the_hello_check_reaches_a_local_bot() -> None:
    with run_client(env="dev") as (client, _, endpoint):
        body = check(client, LOCAL)
        assert body["status"] == "ok" and body["parsed_reply"] == "hello from the bot"
        sent = json.loads(endpoint.requests[0].content)["messages"][0]["content"]
        assert sent == "Hello"


def test_with_env_dev_a_named_local_address_works_too_and_a_wrong_value_changes_nothing() -> None:
    named = {**ENDPOINT, "url": "http://127.0.0.1:3000/api"}
    with run_client(env="development") as (client, _, endpoint):
        assert check(client, named)["status"] == "error" and endpoint.requests == []


def test_turning_it_on_warns_in_the_log(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        with run_client(env="dev"):
            pass
    assert any("ENV=dev" in record.getMessage() for record in caplog.records)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        with run_client():
            pass
    assert not any("ENV=dev" in record.getMessage() for record in caplog.records)
