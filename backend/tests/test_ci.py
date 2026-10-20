"""API tokens and the CI gate (W4), over HTTP with real Postgres.

A token belongs to one setup and can only start runs of that setup and read their results. It is
shown once and stored only as a hash. The gate says pass or fail by a severity threshold and never
claims more than the tests showed.
"""

import json
import time
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from tests.helpers import OWNER, TEST_DB_URL, TitleJudge, wait_for_scan
from tests.test_setup_api import KEY
from tests.test_setup_chat import RoleModel
from tests.test_setup_runs import SlowEndpoint, ready, requests_seen, run_client
from tests.test_setup_tests import answer, interviewer_with, normal_test, one_test
from tests.test_targets import StandIn

# g-1 critical, g-2 medium, g-3 a normal request
MIXED = answer(
    one_test(1, severity="critical"),
    one_test(2, severity="medium"),
    normal_test(1),
)


def roles(generated: str = MIXED) -> RoleModel:
    return RoleModel(interviewer=[interviewer_with()], generator=[generated])


def make_token(client: TestClient, setup_id: int, label: str = "ci") -> dict[str, Any]:
    response = client.post(f"/setups/{setup_id}/ci-tokens", json={"label": label}, headers=OWNER)
    assert response.status_code == 201, response.text
    return dict(response.json())


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def start(client: TestClient, token: str, **body: Any) -> Any:
    payload = {"key": KEY, **body}
    return client.post("/ci/runs", json=payload, headers=bearer(token))


def finish(client: TestClient, token: str, run_id: int, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        body: dict[str, Any] = client.get(f"/ci/runs/{run_id}", headers=bearer(token)).json()
        if body["status"] != "running" or time.monotonic() > deadline:
            return body
        time.sleep(0.05)


# --- the tokens -------------------------------------------------------------------------------


def test_a_token_is_shown_once_listed_without_its_value_and_stored_only_as_a_hash() -> None:
    with run_client(roles=roles()) as (client, _, _):
        setup_id = ready(client)
        created = make_token(client, setup_id, "github")
        token = created["token"]
        assert token.startswith("rf_") and len(token) >= 30 and created["label"] == "github"
        listing = client.get(f"/setups/{setup_id}/ci-tokens", headers=OWNER)
        assert token not in listing.text
        [entry] = listing.json()["tokens"]
        assert entry["id"] == created["id"] and entry["label"] == "github"
        assert entry["revoked"] is False and entry["last_used_at"] is None
        assert "hash" not in json.dumps(entry).lower()
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
                assert not any(token in row[0] for row in rows), table
    finally:
        engine.dispose()


def test_the_owner_manages_tokens_and_the_endpoints_are_locked_for_everyone_else() -> None:
    with run_client(roles=roles()) as (client, _, _):
        setup_id = ready(client)
        assert client.post(f"/setups/{setup_id}/ci-tokens", json={"label": "x"}).status_code == 401
        assert client.get(f"/setups/{setup_id}/ci-tokens").status_code == 401
        assert (
            client.post("/setups/999/ci-tokens", json={"label": "x"}, headers=OWNER).status_code
            == 404
        )
        token = make_token(client, setup_id)
        assert client.delete(f"/setups/{setup_id}/ci-tokens/{token['id']}").status_code == 401
        assert (
            client.delete(f"/setups/{setup_id}/ci-tokens/{token['id']}", headers=OWNER).status_code
            == 204
        )
        [entry] = client.get(f"/setups/{setup_id}/ci-tokens", headers=OWNER).json()["tokens"]
        assert entry["revoked"] is True
        assert client.delete(f"/setups/{setup_id}/ci-tokens/9999", headers=OWNER).status_code == 404


def test_the_ci_endpoints_accept_only_a_live_token_and_not_the_owner_password() -> None:
    with run_client(roles=roles()) as (client, _, _):
        setup_id = ready(client)
        token = make_token(client, setup_id)["token"]
        assert client.post("/ci/runs", json={"key": KEY}).status_code == 401
        assert (
            client.post("/ci/runs", json={"key": KEY}, headers=bearer("rf_not-a-token")).status_code
            == 401
        )
        assert client.post("/ci/runs", json={"key": KEY}, headers=OWNER).status_code == 401
        assert client.get("/ci/runs/1").status_code == 401
        revoked = make_token(client, setup_id, "old")
        client.delete(f"/setups/{setup_id}/ci-tokens/{revoked['id']}", headers=OWNER)
        assert start(client, revoked["token"]).status_code == 401
        assert start(client, token).status_code == 202


def test_a_token_cannot_read_a_scan_of_another_setup_or_a_demo_scan() -> None:
    with run_client(roles=roles()) as (client, _, _):
        first = ready(client)
        token = make_token(client, first)["token"]
        run_id = start(client, token).json()["run_id"]
        finish(client, token, run_id)
        second = ready(client)  # a second setup with its own scan
        other_token = make_token(client, second)["token"]
        assert client.get(f"/ci/runs/{run_id}", headers=bearer(other_token)).status_code == 404
        assert client.get("/ci/runs/99999", headers=bearer(token)).status_code == 404


def test_using_a_token_records_when_it_was_last_used() -> None:
    with run_client(roles=roles()) as (client, _, _):
        setup_id = ready(client)
        created = make_token(client, setup_id)
        finish(client, created["token"], start(client, created["token"]).json()["run_id"])
        [entry] = client.get(f"/setups/{setup_id}/ci-tokens", headers=OWNER).json()["tokens"]
        assert entry["last_used_at"] is not None


# --- starting a run ---------------------------------------------------------------------------


def test_a_run_uses_the_latest_version_and_the_tests_the_owner_left_ticked() -> None:
    with run_client(roles=roles()) as (client, _, endpoint):
        setup_id = ready(client)
        # The owner's last run ticked only g-1 and g-3.
        client.post(
            f"/setups/{setup_id}/versions/1/runs",
            json={"test_ids": ["g-1", "g-3"], "key": KEY},
            headers=OWNER,
        )
        token = make_token(client, setup_id)["token"]
        body = finish(client, token, start(client, token).json()["run_id"])
        sent = [json.loads(r.content)["messages"][0]["content"] for r in requests_seen(endpoint)]
    assert body["status"] == "completed"
    assert [t["test_id"] for t in body["tests"]] == ["g-1", "g-3"]
    assert (
        len(sent) >= 4 and requests_seen(endpoint)[-1].headers["authorization"] == f"Bearer {KEY}"
    )


def test_the_caller_can_choose_the_tests_and_a_bad_choice_runs_nothing() -> None:
    with run_client(roles=roles()) as (client, _, endpoint):
        setup_id = ready(client)
        token = make_token(client, setup_id)["token"]
        refused = start(client, token, test_ids=["g-1", "nope"])
        assert refused.status_code == 422 and refused.json()["error"]["kind"] == "bad_selection"
        assert requests_seen(endpoint) == []
        body = finish(client, token, start(client, token, test_ids=["g-2"]).json()["run_id"])
    assert [t["test_id"] for t in body["tests"]] == ["g-2"]


def test_a_run_needs_generated_tests_and_a_known_version() -> None:
    with run_client(roles=roles()) as (client, _, _):
        from tests.test_setup_tests import confirmed_version

        setup_id = confirmed_version(client)  # confirmed, but no tests generated
        token = make_token(client, setup_id)["token"]
        assert start(client, token).json()["error"]["kind"] == "no_tests"
        assert start(client, token, version=7).status_code == 404


def test_a_run_cannot_start_while_another_scan_is_running() -> None:
    with run_client(stand_in=SlowEndpoint(), roles=roles()) as (client, _, _):
        setup_id = ready(client)
        token = make_token(client, setup_id)["token"]
        first = start(client, token)
        assert first.status_code == 202
        blocked = start(client, token)
        assert blocked.status_code == 409 and blocked.json()["error"]["kind"] == "scan_running"
        finish(client, token, first.json()["run_id"], timeout=60)


# --- the gate ---------------------------------------------------------------------------------


def gate_for(judge: TitleJudge, **body: Any) -> dict[str, Any]:
    with run_client(judge, roles=roles()) as (client, _, _):
        setup_id = ready(client)
        token = make_token(client, setup_id)["token"]
        return finish(client, token, start(client, token, **body).json()["run_id"])


def test_a_critical_failure_fails_the_gate_with_the_reasons() -> None:
    result = gate_for(TitleJudge(fail={"Attack number 1": "It gave in."}))
    gate = result["gate"]
    assert gate["verdict"] == "fail" and gate["fail_on"] == "critical"
    assert gate["reasons"] == ["Attack number 1 (critical): AI judge (FAIL): It gave in."]
    assert result["counts"]["fail"] == 1
    assert [f["test_id"] for f in result["failures"]] == ["g-1"]
    assert result["failures"][0]["severity"] == "critical"


def test_a_failure_below_the_threshold_does_not_fail_the_gate_but_is_still_reported() -> None:
    result = gate_for(TitleJudge(fail={"Attack number 2": "Gave a little."}))  # medium
    assert result["gate"]["verdict"] == "pass"
    assert result["counts"]["fail"] == 1 and [f["test_id"] for f in result["failures"]] == ["g-2"]
    assert "1 test failed below" in result["gate"]["message"]


def test_the_threshold_is_chosen_by_the_caller() -> None:
    judge = TitleJudge(fail={"Attack number 2": "Gave a little."})
    assert gate_for(judge, fail_on="medium")["gate"]["verdict"] == "fail"
    assert gate_for(judge, fail_on="any")["gate"]["verdict"] == "fail"
    assert gate_for(judge, fail_on="high")["gate"]["verdict"] == "pass"


def test_a_bad_threshold_is_refused() -> None:
    with run_client(roles=roles()) as (client, _, _):
        setup_id = ready(client)
        token = make_token(client, setup_id)["token"]
        refused = start(client, token, fail_on="whenever")
        assert refused.status_code == 422 and refused.json()["error"]["kind"] == "bad_threshold"


def test_unclear_tests_are_counted_and_can_fail_the_gate_if_the_caller_asks() -> None:
    judge = TitleJudge(garbage={"Attack number 2"})  # the judge cannot decide this one
    lenient = gate_for(judge)
    assert lenient["gate"]["verdict"] == "pass" and lenient["counts"]["inconclusive"] == 1
    assert "1 test was unclear" in lenient["gate"]["message"]
    strict = gate_for(judge, fail_on_unclear=True)
    assert strict["gate"]["verdict"] == "fail"
    assert any("unclear" in reason.lower() for reason in strict["gate"]["reasons"])


def test_a_clean_run_passes_and_never_calls_the_bot_safe() -> None:
    result = gate_for(TitleJudge())
    assert result["gate"]["verdict"] == "pass" and result["counts"]["fail"] == 0
    text_ = json.dumps(result["gate"])
    assert "This is not a guarantee of security" in result["gate"]["message"]
    assert not any(
        word in text_.lower().replace("not a guarantee of security", "")
        for word in (" safe", "secure", " ready")
    )


def test_a_run_where_no_test_could_be_completed_does_not_pass() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["messages"][-1]["content"] == "Hello":
            return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})
        return httpx.Response(500, text="boom")

    with run_client(TitleJudge(), StandIn(handler), roles=roles()) as (client, _, _):
        setup_id = ready(client)
        token = make_token(client, setup_id)["token"]
        result = finish(client, token, start(client, token).json()["run_id"])
    assert result["counts"]["error"] == 3
    assert result["gate"]["verdict"] == "error"
    assert "could not be completed" in result["gate"]["message"].lower()


def test_while_the_run_is_going_the_gate_says_so() -> None:
    with run_client(stand_in=SlowEndpoint(), roles=roles()) as (client, _, _):
        setup_id = ready(client)
        token = make_token(client, setup_id)["token"]
        run_id = start(client, token).json()["run_id"]
        early = client.get(f"/ci/runs/{run_id}", headers=bearer(token)).json()
        assert early["status"] == "running" and early["gate"]["verdict"] == "running"
        finish(client, token, run_id, timeout=60)


def test_the_key_is_not_in_the_result_or_the_database() -> None:
    with run_client(roles=roles()) as (client, _, _):
        setup_id = ready(client)
        token = make_token(client, setup_id)["token"]
        result = finish(client, token, start(client, token).json()["run_id"])
        assert KEY not in json.dumps(result)
        scan = wait_for_scan(client, result["run_id"])
        assert KEY not in json.dumps(scan)
