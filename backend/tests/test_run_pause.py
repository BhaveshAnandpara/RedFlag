"""A run when the bot stops answering: wait longer, ask once more, then pause for a person.

Over HTTP with real Postgres. The bot is a stand-in that can be told to fail, to time out, or to
go down, so each way a real bot fails is tried. The models are the same scripted stand-ins as in
the other tests.
"""

import json
import time
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from redflag_backend.scan.store import ScanStore
from redflag_backend.settings import Settings
from tests.helpers import TEST_DB_URL
from tests.test_multi_turn import GaveInJudge
from tests.test_plan_run import made_plan, proofs, run_plan, small
from tests.test_quick_scan import quick
from tests.test_setup_runs import finished, ready, run_client
from tests.test_targets import StandIn, openai_reply

FAST: dict[str, Any] = {"run_retry_pause_seconds": 0.0}


class Bot(StandIn):
    """A bot that refuses every attack, unless told to fail. Requests are counted from 1, not
    counting the hello, so a test can say "the 3rd message fails"."""

    def __init__(self) -> None:
        super().__init__(self._answer)
        self.down = False
        self.down_after: int | None = None
        self.fail_at: set[int] = set()
        self.timeout_at: set[int] = set()
        self.seen = 0
        self.read_timeouts: list[float] = []
        self.hello_timeout = 0.0

    def _answer(self, request: httpx.Request) -> httpx.Response:
        timeout = request.extensions["timeout"]["read"]
        content = json.loads(request.content)["messages"][-1]["content"]
        if content == "Hello":
            self.hello_timeout = timeout
            return openai_reply("hello from the bot")
        self.seen += 1
        self.read_timeouts.append(timeout)
        if self.down or (self.down_after is not None and self.seen > self.down_after):
            return httpx.Response(500, text="boom")
        if self.seen in self.fail_at:
            return httpx.Response(500, text="boom")
        if self.seen in self.timeout_at:
            raise httpx.ReadTimeout("slow", request=request)
        return openai_reply("I can't help with that.")


def read(client: TestClient, scan_id: int, key: str) -> dict[str, Any]:
    body: dict[str, Any] = client.get(f"/open-scans/{scan_id}", params={"key": key}).json()
    return body


def wait_until(client: TestClient, scan_id: int, key: str, status: str) -> dict[str, Any]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        body = read(client, scan_id, key)
        if body["scan"]["status"] == status:
            return body
        time.sleep(0.05)
    raise AssertionError(f"the scan never became {status}: {read(client, scan_id, key)['scan']}")


def answer(client: TestClient, scan_id: int, key: str, action: str) -> Any:
    return client.post(
        f"/open-scans/{scan_id}/answer", params={"key": key}, json={"action": action}
    )


def begin(client: TestClient, **changes: Any) -> tuple[int, str, int]:
    """Make a plan and start running it. Returns the scan id, its view key, and the test count."""
    plan_id = made_plan(client)
    info = run_plan(client, plan_id, **changes).json()
    return int(info["scan_id"]), str(info["view_key"]), int(info["test_count"])


# --- a reply that never comes ----------------------------------------------------------------


def test_a_reply_that_never_comes_is_asked_for_once_more_and_a_slow_bot_gets_through() -> None:
    bot = Bot()
    bot.timeout_at = {2}  # the second message is never answered, the one after it is
    with run_client(GaveInJudge(), bot, roles=small(), **FAST) as (client, _, _):
        scan_id, key, count = begin(client)
        body = wait_until(client, scan_id, key, "completed")
    results = body["results"]
    assert len(results) == count
    assert all(r["status"] == "pass" for r in results), [
        (r["status"], r["evidence"][:90]) for r in results
    ]
    # one more request than the run would otherwise have sent: the second ask
    clean = Bot()
    with run_client(GaveInJudge(), clean, roles=small(), **FAST) as (client, _, _):
        scan_id, key, _ = begin(client)
        wait_until(client, scan_id, key, "completed")
    assert bot.seen == clean.seen + 1


def test_a_reply_that_never_comes_twice_is_no_answer_and_never_held_or_broke() -> None:
    bot = Bot()
    bot.timeout_at = set(range(1, 400))
    with run_client(GaveInJudge(), bot, roles=small(), **FAST) as (client, _, _):
        scan_id, key, _ = begin(client)
        wait_until(client, scan_id, key, "paused")
        # each test asked twice: the first time, and once more
        assert bot.seen == 3 * 2
        assert answer(client, scan_id, key, "stop").status_code == 200
        body = wait_until(client, scan_id, key, "interrupted")
    held = [r for r in body["results"] if "timed out" in r["evidence"]]
    assert len(held) == 3 and {r["status"] for r in body["results"]} == {"error"}


def test_the_run_waits_as_long_for_a_reply_as_it_is_told_and_the_hello_check_does_not() -> None:
    bot = Bot()
    with run_client(GaveInJudge(), bot, roles=small(), run_reply_timeout_seconds=37.0, **FAST) as (
        client,
        _,
        _,
    ):
        scan_id, key, _ = begin(client)
        wait_until(client, scan_id, key, "completed")
    assert set(bot.read_timeouts) == {37.0}
    assert bot.hello_timeout == 20.0  # checking the address stays quick


# --- a bot that stops answering --------------------------------------------------------------


def test_three_tests_in_a_row_with_no_answer_pause_the_run_and_nothing_more_is_sent() -> None:
    bot = Bot()
    bot.down = True
    with run_client(GaveInJudge(), bot, roles=small(), **FAST) as (client, _, _):
        scan_id, key, _ = begin(client)
        body = wait_until(client, scan_id, key, "paused")
        sent = bot.seen
        time.sleep(0.5)
        assert bot.seen == sent == 3  # one message per test, no more once it is paused
        note = body["scan"]["note"]
        assert "Your bot stopped answering" in note and "press Retry" in note
        assert body["results"] == []  # kept aside until it is known whether the bot is back
        answer(client, scan_id, key, "stop")
        wait_until(client, scan_id, key, "interrupted")


def test_retry_asks_the_same_tests_again_and_the_run_carries_on_when_the_bot_is_back() -> None:
    bot = Bot()
    bot.down = True
    with run_client(GaveInJudge(), bot, roles=small(), **FAST) as (client, _, _):
        scan_id, key, count = begin(client)
        wait_until(client, scan_id, key, "paused")
        bot.down = False
        assert answer(client, scan_id, key, "retry").status_code == 200
        body = wait_until(client, scan_id, key, "completed")
    results = body["results"]
    assert len(results) == count and body["scan"]["note"] is None
    assert {r["status"] for r in results} == {"pass"}  # the three that failed were asked again
    assert len({r["test_id"] for r in results}) == count  # each test once, none doubled


def test_stop_keeps_what_was_tested_and_says_which_tests_were_not_run() -> None:
    bot = Bot()
    bot.down_after = 4  # two conversations of two turns, then the bot is gone
    with run_client(GaveInJudge(), bot, roles=small(), **FAST) as (client, _, _):
        scan_id, key, count = begin(client)
        wait_until(client, scan_id, key, "paused")
        assert answer(client, scan_id, key, "stop").status_code == 200
        body = wait_until(client, scan_id, key, "interrupted")
        saved = proofs(scan_id)
    results = body["results"]
    assert len(results) == count  # the counts still add up to the plan
    assert [r["status"] for r in results[:2]] == ["pass", "pass"]
    refused = [r for r in results if "status 500" in r["evidence"]]
    not_run = [r for r in results if r["evidence"].startswith("Not run: you stopped the run")]
    assert len(refused) == 3 and len(not_run) == count - 5
    assert "stopped after your bot stopped answering" in body["scan"]["note"]
    left = count - 5
    assert ("1 test was not run" if left == 1 else f"{left} tests were not run") in body["scan"][
        "note"
    ]
    assert "Everything tested before is kept" in body["scan"]["note"]
    assert len(saved) == 5  # proof for what was tested or tried, not for what never ran


def test_a_blip_of_two_tests_is_not_a_pause_and_they_are_saved_as_they_were() -> None:
    bot = Bot()
    bot.fail_at = {3, 4}  # the second and third tests each get an error, then the bot is fine
    with run_client(GaveInJudge(), bot, roles=small(), **FAST) as (client, _, _):
        scan_id, key, count = begin(client)
        body = wait_until(client, scan_id, key, "completed")
    results = body["results"]
    assert len(results) == count
    assert [r["status"] for r in results].count("error") == 2
    assert [r["test_id"] for r in results] == [f"p-{n}" for n in range(1, count + 1)]
    assert all(r["status"] == "pass" for r in results if r["status"] != "error")


def test_a_run_nobody_answers_is_stopped_so_it_cannot_block_every_other_scan() -> None:
    bot = Bot()
    bot.down = True
    with run_client(GaveInJudge(), bot, roles=small(), run_pause_timeout_seconds=0.3, **FAST) as (
        client,
        _,
        _,
    ):
        scan_id, key, count = begin(client)
        body = wait_until(client, scan_id, key, "interrupted")
        assert "nobody answered for a while" in body["scan"]["note"]
        assert len(body["results"]) == count
        again = quick(client)  # another scan can start: the gate is free
        assert again.status_code == 202


# --- who may answer ---------------------------------------------------------------------------


def test_only_the_scans_own_key_can_answer_and_only_while_it_waits() -> None:
    bot = Bot()
    bot.down = True
    with run_client(GaveInJudge(), bot, roles=small(), **FAST) as (client, _, _):
        scan_id, key, _ = begin(client)
        wait_until(client, scan_id, key, "paused")
        assert answer(client, scan_id, "not-the-key", "retry").status_code == 404
        assert answer(client, 99999, key, "retry").status_code == 404
        assert answer(client, scan_id, key, "explode").status_code == 422
        assert read(client, scan_id, key)["scan"]["status"] == "paused"  # nothing changed
        answer(client, scan_id, key, "stop")
        wait_until(client, scan_id, key, "interrupted")
        done = answer(client, scan_id, key, "retry")
        assert done.status_code == 409 and done.json()["error"]["kind"] == "not_waiting"


def test_a_run_that_is_not_waiting_cannot_be_answered() -> None:
    with run_client(GaveInJudge(), Bot(), roles=small(), **FAST) as (client, _, _):
        scan_id, key, _ = begin(client)
        wait_until(client, scan_id, key, "completed")
        refused = answer(client, scan_id, key, "stop")
        assert refused.status_code == 409 and refused.json()["error"]["kind"] == "not_waiting"


# --- who can pause ----------------------------------------------------------------------------


def test_a_standard_run_from_the_open_page_pauses_too_when_the_bot_stops_answering() -> None:
    bot = Bot()
    bot.down = True
    with run_client(GaveInJudge(), bot, roles=small(), **FAST) as (client, _, _):
        info = quick(client).json()  # no plan: the standard tests
        wait_until(client, info["scan_id"], info["view_key"], "paused")
        assert bot.seen == 3
        answer(client, info["scan_id"], info["view_key"], "stop")
        body = wait_until(client, info["scan_id"], info["view_key"], "interrupted")
    assert len(body["results"]) == 31  # the standard pack, every test accounted for


def test_a_run_started_from_the_owners_page_never_pauses_because_nobody_could_answer() -> None:
    bot = Bot()
    bot.down = True
    with run_client(GaveInJudge(), bot, **FAST) as (client, _, _):
        setup_id = ready(client)
        scan = finished(client, setup_id, ["g-1", "g-2", "g-3"])
    assert scan["scan"]["status"] == "completed"
    assert [r["status"] for r in scan["results"]] == ["error", "error", "error"]


def test_the_proof_of_a_failed_normal_request_does_not_say_the_bot_broke() -> None:
    from redflag_backend.supervisor.run_tests import record_for

    test = {
        "spec_id": "spec-x",
        "spec_hash": "h",
        "goal": "Say the opening hours.",
        "kind": "positive",
    }
    run = {
        "status": "fail",
        "evidence": "AI judge (FAIL).",
        "message": "Hours?",
        "reply": "9 to 5.",
    }
    failed = record_for(test, [run], run)
    assert failed.outcome == "broke" and failed.what_happened.startswith("Your bot failed a normal")
    ok = {**run, "status": "pass"}
    assert record_for(test, [ok], ok).what_happened.startswith("Your bot handled a normal request")
    attack = {**test, "kind": "negative"}
    assert record_for(attack, [run], run).what_happened.startswith("Your bot broke: ")


# --- the store, and how patient the models are --------------------------------------------------


def test_a_run_that_was_waiting_when_the_backend_stopped_is_stopped_on_the_next_start() -> None:
    store = ScanStore(create_engine(TEST_DB_URL))
    project = store.ensure_project("pause-bot", "Pause bot", "")
    waiting = store.create_scan(project, {}, 100.0)
    running = store.create_scan(project, {}, 100.0)
    store.pause_scan(waiting, "Your bot stopped answering.", 200.0)
    found = store.get_scan(waiting)
    assert found is not None and found["scan"]["status"] == "paused"
    assert store.interrupt_stale(10_000.0, 300.0) == 1  # a paused run is not stale: only `running`
    assert store.interrupt_paused(300.0) == 1
    after = store.get_scan(waiting)
    assert after is not None and after["scan"]["status"] == "interrupted"
    assert "restarted while this run was waiting" in after["scan"]["note"]
    other = store.get_scan(running)
    assert other is not None and other["scan"]["status"] == "interrupted"  # the stale one


def test_a_paused_run_can_be_resumed_and_a_finished_one_cannot() -> None:
    store = ScanStore(create_engine(TEST_DB_URL))
    project = store.ensure_project("resume-bot", "Resume bot", "")
    scan_id = store.create_scan(project, {}, 100.0)
    store.pause_scan(scan_id, "waiting", 150.0)
    store.resume_scan(scan_id, 160.0)
    found = store.get_scan(scan_id)
    assert found is not None and found["scan"]["status"] == "running"
    assert found["scan"]["note"] is None
    store.finish_scan(scan_id, "completed", 170.0)
    store.pause_scan(scan_id, "too late", 180.0)  # a finished scan is left alone
    done = store.get_scan(scan_id)
    assert done is not None and done["scan"]["status"] == "completed"


def test_the_judge_and_the_attacker_wait_longer_for_the_models_quota() -> None:
    settings = Settings(database_url=TEST_DB_URL, frontend_origin="http://localhost:3001")
    assert settings.scan_rate_limit_retries == 6
    assert (settings.attacker_rate_wait_seconds, settings.attacker_rate_retries) == (30.0, 6)
    assert settings.run_reply_timeout_seconds == 60.0 and settings.run_pause_after_failures == 3
