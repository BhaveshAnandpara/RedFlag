"""The setup drafts and versions over HTTP, with real Postgres.

A setup is what the owner tells Redflag about a bot. The only faked parts are the outside models
and the user's endpoint (a stand-in at the HTTP boundary). The endpoint key must never be saved.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from redflag_backend.app import create_app
from redflag_backend.settings import Settings
from tests.helpers import OWNER, OWNER_TOKEN, TEST_DB_URL
from tests.test_targets import PUBLIC_IP, StandIn, openai_reply, resolver

KEY = "unique-endpoint-key-8a7b6c5d"


@contextmanager
def setup_client(stand_in: StandIn | None = None) -> Iterator[TestClient]:
    server = stand_in or StandIn()
    app = create_app(
        Settings(
            database_url=TEST_DB_URL,
            frontend_origin="http://localhost:3000",
            owner_token=OWNER_TOKEN,
        ),
        providers=[],
        bot_providers=[],
        target_transport=server.transport(),
        target_resolver=resolver({"bot.example": [PUBLIC_IP]}),
    )
    with TestClient(app) as client:
        yield client


def new_setup(client: TestClient) -> int:
    response = client.post("/setups", headers=OWNER)
    assert response.status_code == 201, response.text
    return int(response.json()["setup_id"])


def get(client: TestClient, setup_id: int) -> dict[str, Any]:
    response = client.get(f"/setups/{setup_id}", headers=OWNER)
    assert response.status_code == 200, response.text
    return dict(response.json())


def point_at_bot(client: TestClient, setup_id: int, url: str = "https://bot.example/chat") -> None:
    assert (
        client.put(f"/setups/{setup_id}/endpoint", json={"url": url}, headers=OWNER).status_code
        == 200
    )


def run_connection_test(client: TestClient, setup_id: int) -> httpx.Response:
    response: httpx.Response = client.post(
        f"/setups/{setup_id}/connection-test", json={"key": KEY}, headers=OWNER
    )
    return response


def add_rule(client: TestClient, setup_id: int, **changes: Any) -> dict[str, Any]:
    body = {"text": "Must never transfer money.", "kind": "forbidden", "severity": "critical"}
    body.update(changes)
    response = client.post(f"/setups/{setup_id}/rules", json=body, headers=OWNER)
    assert response.status_code == 201, response.text
    return dict(response.json())


def make_ready(client: TestClient, setup_id: int) -> None:
    point_at_bot(client, setup_id)
    assert run_connection_test(client, setup_id).json()["status"] == "ok"
    assert (
        client.put(
            f"/setups/{setup_id}/purpose",
            json={"value": "A bank support assistant."},
            headers=OWNER,
        ).status_code
        == 200
    )
    add_rule(client, setup_id)


# --- the owner lock -----------------------------------------------------------------------


def test_every_setup_endpoint_is_locked_without_the_owner_password() -> None:
    with setup_client() as client:
        assert client.post("/setups").status_code == 401
        assert client.get("/setups/1").status_code == 401
        wrong = {"X-Owner-Token": "wrong"}
        assert client.post("/setups", headers=wrong).status_code == 401
        setup_id = new_setup(client)
        for method, path in [
            ("get", f"/setups/{setup_id}"),
            ("put", f"/setups/{setup_id}/purpose"),
            ("post", f"/setups/{setup_id}/rules"),
            ("put", f"/setups/{setup_id}/endpoint"),
            ("post", f"/setups/{setup_id}/connection-test"),
            ("post", f"/setups/{setup_id}/confirm"),
            ("get", f"/setups/{setup_id}/versions"),
        ]:
            assert getattr(client, method)(path).status_code == 401, path


# --- drafts -------------------------------------------------------------------------------


def test_a_new_draft_is_empty_and_nothing_is_required_yet_met() -> None:
    with setup_client() as client:
        setup = get(client, new_setup(client))
    assert setup["fields"]["purpose"]["value"] == ""
    assert setup["fields"]["rules"] == []
    assert setup["required"] == {
        "connection": False,
        "purpose": False,
        "forbidden_rule": False,
        "ready": False,
    }


def test_a_draft_survives_a_restart_of_the_app() -> None:
    with setup_client() as client:
        setup_id = new_setup(client)
        client.put(f"/setups/{setup_id}/purpose", json={"value": "A travel agent."}, headers=OWNER)
        add_rule(client, setup_id, text="Never book without payment.")
    with setup_client() as fresh:
        setup = get(fresh, setup_id)
    assert setup["fields"]["purpose"]["value"] == "A travel agent."
    assert [r["text"] for r in setup["fields"]["rules"]] == ["Never book without payment."]


def test_the_owners_edit_is_locked_and_can_be_unlocked() -> None:
    with setup_client() as client:
        setup_id = new_setup(client)
        client.put(f"/setups/{setup_id}/purpose", json={"value": "My words."}, headers=OWNER)
        purpose = get(client, setup_id)["fields"]["purpose"]
        assert purpose == {"value": "My words.", "source": "edited", "locked": True}
        client.post(f"/setups/{setup_id}/purpose/unlock", headers=OWNER)
        assert get(client, setup_id)["fields"]["purpose"]["locked"] is False
        assert get(client, setup_id)["fields"]["purpose"]["value"] == "My words."


def test_rules_can_be_added_edited_confirmed_and_deleted() -> None:
    with setup_client() as client:
        setup_id = new_setup(client)
        rule = add_rule(client, setup_id, text="Never give advice.", status="unclear")
        assert rule["source"] == "user" and rule["status"] == "unclear"
        edited = client.put(
            f"/setups/{setup_id}/rules/{rule['id']}",
            json={"text": "Never give investment advice.", "severity": "medium"},
            headers=OWNER,
        ).json()
        assert edited["text"] == "Never give investment advice." and edited["locked"] is True
        confirmed = client.post(
            f"/setups/{setup_id}/rules/{rule['id']}/confirm", headers=OWNER
        ).json()
        assert confirmed["status"] == "stated"
        assert (
            client.delete(f"/setups/{setup_id}/rules/{rule['id']}", headers=OWNER).status_code
            == 204
        )
        assert get(client, setup_id)["fields"]["rules"] == []
        missing = client.delete(f"/setups/{setup_id}/rules/nope", headers=OWNER)
        assert missing.status_code == 404


def test_an_unknown_setup_is_404() -> None:
    with setup_client() as client:
        assert client.get("/setups/9999", headers=OWNER).status_code == 404


# --- the connection test and the required items -------------------------------------------


def test_a_good_connection_test_is_remembered_and_the_key_is_never_returned() -> None:
    with setup_client() as client:
        setup_id = new_setup(client)
        point_at_bot(client, setup_id)
        response = run_connection_test(client, setup_id)
        body = response.json()
        assert response.status_code == 200 and body["status"] == "ok"
        assert body["parsed_reply"] == "hello from the bot" and body["attempts_left"] == 4
        assert KEY not in response.text
        setup = get(client, setup_id)
        assert setup["connection"]["ok"] is True and KEY not in str(setup)
        assert setup["required"]["connection"] is True


def test_a_failed_connection_test_says_why_and_is_not_remembered() -> None:
    server = StandIn(lambda request: httpx.Response(401, text="nope"))
    with setup_client(server) as client:
        setup_id = new_setup(client)
        point_at_bot(client, setup_id)
        body = run_connection_test(client, setup_id).json()
        assert body["status"] == "error" and body["http_status"] == 401
        assert get(client, setup_id)["connection"]["ok"] is False


def test_an_internal_address_is_refused_and_never_called() -> None:
    server = StandIn()
    with setup_client(server) as client:
        setup_id = new_setup(client)
        point_at_bot(client, setup_id, url="http://127.0.0.1:8000/chat")
        body = run_connection_test(client, setup_id).json()
        assert body["status"] == "error" and "not allowed" in body["error"]
        assert server.requests == []


def test_there_is_a_limit_on_connection_tests_per_setup() -> None:
    server = StandIn()
    with setup_client(server) as client:
        setup_id = new_setup(client)
        point_at_bot(client, setup_id)
        for _ in range(5):
            assert run_connection_test(client, setup_id).status_code == 200
        sixth = run_connection_test(client, setup_id)
        assert sixth.status_code == 429 and sixth.json()["error"]["kind"] == "too_many_tests"
        assert len(server.requests) == 5


def test_changing_the_endpoint_forgets_that_the_connection_worked() -> None:
    with setup_client() as client:
        setup_id = new_setup(client)
        point_at_bot(client, setup_id)
        run_connection_test(client, setup_id)
        assert get(client, setup_id)["connection"]["ok"] is True
        point_at_bot(client, setup_id, url="https://bot.example/other")
        assert get(client, setup_id)["connection"]["ok"] is False


def test_the_required_items_unlock_only_with_a_user_stated_forbidden_rule() -> None:
    with setup_client() as client:
        setup_id = new_setup(client)
        point_at_bot(client, setup_id)
        run_connection_test(client, setup_id)
        client.put(f"/setups/{setup_id}/purpose", json={"value": "A shop bot."}, headers=OWNER)
        add_rule(client, setup_id, kind="allowed", text="May show the user's own orders.")
        assert get(client, setup_id)["required"]["forbidden_rule"] is False  # allowed rule
        unsure = add_rule(client, setup_id, text="Maybe no advice.", status="unclear")
        required = get(client, setup_id)["required"]
        assert required["forbidden_rule"] is False and required["ready"] is False  # unclear rule
        client.post(f"/setups/{setup_id}/rules/{unsure['id']}/confirm", headers=OWNER)
        required = get(client, setup_id)["required"]
        assert required == {
            "connection": True, "purpose": True, "forbidden_rule": True, "ready": True,
        }  # fmt: skip


# --- confirming and versions --------------------------------------------------------------


def test_confirming_is_refused_until_the_required_items_are_met_and_says_which() -> None:
    with setup_client() as client:
        setup_id = new_setup(client)
        refused = client.post(f"/setups/{setup_id}/confirm", headers=OWNER)
        assert refused.status_code == 409
        error = refused.json()["error"]
        assert error["kind"] == "not_ready"
        assert set(error["missing"]) == {"connection", "purpose", "forbidden_rule"}
        assert client.get(f"/setups/{setup_id}/versions", headers=OWNER).json()["versions"] == []


def test_confirming_saves_numbered_immutable_versions() -> None:
    with setup_client() as client:
        setup_id = new_setup(client)
        make_ready(client, setup_id)
        first = client.post(f"/setups/{setup_id}/confirm", headers=OWNER)
        assert first.status_code == 201 and first.json()["version"] == 1
        client.put(f"/setups/{setup_id}/purpose", json={"value": "Changed purpose."}, headers=OWNER)
        add_rule(client, setup_id, text="Never reveal account numbers.")
        second = client.post(f"/setups/{setup_id}/confirm", headers=OWNER)
        assert second.json()["version"] == 2
        listing = client.get(f"/setups/{setup_id}/versions", headers=OWNER).json()["versions"]
        assert [v["number"] for v in listing] == [1, 2]
        one = client.get(f"/setups/{setup_id}/versions/1", headers=OWNER).json()
        two = client.get(f"/setups/{setup_id}/versions/2", headers=OWNER).json()
        assert one["fields"]["purpose"]["value"] == "A bank support assistant."
        assert len(one["fields"]["rules"]) == 1
        assert two["fields"]["purpose"]["value"] == "Changed purpose."
        assert len(two["fields"]["rules"]) == 2


def test_a_saved_version_never_changes_when_the_draft_is_edited() -> None:
    with setup_client() as client:
        setup_id = new_setup(client)
        make_ready(client, setup_id)
        client.post(f"/setups/{setup_id}/confirm", headers=OWNER)
        client.put(f"/setups/{setup_id}/purpose", json={"value": "Edited later."}, headers=OWNER)
        one = client.get(f"/setups/{setup_id}/versions/1", headers=OWNER).json()
        assert one["fields"]["purpose"]["value"] == "A bank support assistant."
        assert client.get(f"/setups/{setup_id}/versions/9", headers=OWNER).status_code == 404


def test_each_setup_is_its_own_project() -> None:
    with setup_client() as client:
        first, second = new_setup(client), new_setup(client)
        assert first != second
        assert get(client, first)["project_slug"] != get(client, second)["project_slug"]
        assert get(client, first)["project_slug"].startswith("target-")


# --- the key is never saved ---------------------------------------------------------------


def test_the_endpoint_key_is_in_no_table_after_a_full_session() -> None:
    with setup_client(StandIn(lambda request: openai_reply(f"hi {KEY}"))) as client:
        setup_id = new_setup(client)
        make_ready(client, setup_id)
        client.post(f"/setups/{setup_id}/confirm", headers=OWNER)
        assert KEY not in client.get(f"/setups/{setup_id}", headers=OWNER).text
        assert KEY not in client.get(f"/setups/{setup_id}/versions/1", headers=OWNER).text
    engine = create_engine(TEST_DB_URL)
    try:
        with engine.connect() as conn:
            tables = [
                row[0]
                for row in conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            ]
            for table in tables:
                rows = conn.execute(text(f'SELECT t::text FROM "{table}" t')).all()  # noqa: S608
                assert not any(KEY in row[0] for row in rows), table
    finally:
        engine.dispose()
