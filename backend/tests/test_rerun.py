"""Run again (W3): a new scan with the same setup version and the same ticked tests, and a pointer
to the scan before it, so the page can show what changed.
"""

import json
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from tests.helpers import (
    OWNER,
    TEST_DB_URL,
    GullibleProvider,
    SlowProvider,
    run_scan,
    scan_client,
    wait_for_scan,
)
from tests.test_setup_api import KEY
from tests.test_setup_chat import RoleModel
from tests.test_setup_runs import finished, ready, requests_seen, run_client
from tests.test_setup_tests import GOOD, answer, generate, interviewer_with, normal_test, one_test


def rerun(client: TestClient, scan_id: int, key: str | None = KEY) -> Any:
    return client.post(f"/scans/{scan_id}/rerun", json={"key": key}, headers=OWNER)


def test_run_again_starts_a_new_scan_with_the_same_version_and_the_same_ticked_tests() -> None:
    with run_client() as (client, judge, endpoint):
        setup_id = ready(client)
        first = finished(client, setup_id, ["g-1", "g-3"])
        started = rerun(client, first["scan"]["id"])
        assert started.status_code == 202
        second = wait_for_scan(client, started.json()["scan_id"])
        sent = [json.loads(r.content)["messages"][0]["content"] for r in requests_seen(endpoint)]
    assert second["scan"]["id"] != first["scan"]["id"]
    assert second["scan"]["bot_id"] == first["scan"]["bot_id"]  # the same project
    assert [r["test_id"] for r in second["results"]] == ["g-1", "g-3"]
    assert second["scan"]["settings"]["setup"]["version"] == 1
    assert second["scan"]["settings"]["setup"]["selected_test_ids"] == ["g-1", "g-3"]
    assert second["scan"]["settings"]["setup"]["rerun_of"] == first["scan"]["id"]
    assert len(sent) == 4 and sent[:2] == sent[2:]  # the same two messages, sent twice


def test_the_key_comes_with_the_request_and_is_saved_nowhere() -> None:
    with run_client() as (client, _, endpoint):
        setup_id = ready(client)
        first = finished(client, setup_id, ["g-1"])
        started = rerun(client, first["scan"]["id"], key=KEY)
        second = wait_for_scan(client, started.json()["scan_id"])
        assert requests_seen(endpoint)[-1].headers["authorization"] == f"Bearer {KEY}"
        assert KEY not in json.dumps(second)
    engine = create_engine(TEST_DB_URL)
    try:
        with engine.connect() as conn:
            tables = [
                r[0]
                for r in conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            ]
            for table in tables:
                rows = conn.execute(text(f'SELECT t::text FROM "{table}" t')).all()  # noqa: S608
                assert not any(KEY in row[0] for row in rows), table
    finally:
        engine.dispose()


def test_a_demo_bot_scan_cannot_be_run_again_this_way_and_an_unknown_scan_is_404() -> None:
    with scan_client([GullibleProvider()]) as client:
        demo = run_scan(client, "acme-weak")
        refused = rerun(client, demo["scan"]["id"])
        assert refused.status_code == 422 and refused.json()["error"]["kind"] == "not_a_setup_scan"
        assert rerun(client, 9999).status_code == 404
        assert client.post("/scans/1/rerun", json={}).status_code == 401


def test_run_again_is_refused_while_another_scan_is_running() -> None:
    with run_client() as (client, _, _):
        setup_id = ready(client)
        first = finished(client, setup_id, ["g-1"])
    slow = SlowProvider("slow")
    with run_client(bot_providers=[slow]) as (client, _, _):
        setup_id = ready(client)
        done = finished(client, setup_id, ["g-1"])
        demo = client.post("/scans", json={"bot_id": "acme-weak"}, headers=OWNER)
        assert demo.status_code == 202
        blocked = rerun(client, done["scan"]["id"])
        assert blocked.status_code == 409 and blocked.json()["error"]["kind"] == "scan_running"
        wait_for_scan(client, demo.json()["scan_id"], timeout=60)
    assert first["scan"]["status"] == "completed"


def test_run_again_is_refused_when_the_tests_it_ran_no_longer_exist() -> None:
    roles = RoleModel(
        interviewer=[interviewer_with()],
        generator=[GOOD, answer(one_test(1), normal_test(1))],  # the second time: only two tests
    )
    with run_client(roles=roles) as (client, _, endpoint):
        setup_id = ready(client)
        first = finished(client, setup_id, ["g-1", "g-3"])
        assert generate(client, setup_id).status_code == 201  # replaces the tests: g-1 and g-2 only
        before = len(endpoint.requests)
        refused = rerun(client, first["scan"]["id"])
        assert refused.status_code == 422 and refused.json()["error"]["kind"] == "bad_selection"
        assert len(endpoint.requests) == before


def test_each_scan_points_at_the_previous_scan_of_the_same_project() -> None:
    with run_client() as (client, _, _):
        setup_id = ready(client)
        first = finished(client, setup_id, ["g-1"])
        assert first["scan"]["previous_scan_id"] is None
        started = rerun(client, first["scan"]["id"])
        second = wait_for_scan(client, started.json()["scan_id"])
        assert second["scan"]["previous_scan_id"] == first["scan"]["id"]
        third = wait_for_scan(client, rerun(client, second["scan"]["id"]).json()["scan_id"])
        assert third["scan"]["previous_scan_id"] == second["scan"]["id"]


def test_demo_bot_scans_also_know_their_previous_scan_but_only_of_the_same_bot() -> None:
    with scan_client([GullibleProvider()]) as client:
        weak_one = run_scan(client, "acme-weak")
        hardened = run_scan(client, "acme-hardened")
        weak_two = run_scan(client, "acme-weak")
    assert weak_one["scan"]["previous_scan_id"] is None
    assert hardened["scan"]["previous_scan_id"] is None  # a different bot
    assert weak_two["scan"]["previous_scan_id"] == weak_one["scan"]["id"]
