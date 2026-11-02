"""Running a plan: turning its tests into what the runner executes, and saving the proof of each.

The plan holds test specs written by the personas. The runner executes plain test dictionaries,
so each spec is turned into one, with its own turn limit and the number of times to run it. Every
spec is saved and locked first, so a result can say exactly which test it proves.
"""

import asyncio
from typing import Any

from redflag_backend.attacks.disguises import technique_name
from redflag_backend.scan.target_runner import TestDone, representative
from redflag_backend.specs.contract import DECIDED, Outcome, ResultRecord
from redflag_backend.specs.oracle import Turn
from redflag_backend.specs.results import ResultStore
from redflag_backend.specs.spec import TestSpec
from redflag_backend.specs.store import SpecStore, StoredSpec
from redflag_backend.supervisor.goals import Goal
from redflag_backend.supervisor.plan import Plan

MAX_RUNS = 5
TITLE_CHARS = 140


def planned(plan: Plan) -> list[tuple[Goal, TestSpec]]:
    """Every test in the plan, in the order the plan shows them."""
    return [(p.goal, spec) for p in plan.goals for spec in p.specs]


def runs_for(spec: TestSpec, runs: int) -> int:
    """How many times a test runs, when each attack may run up to `runs` times (1 to 5). A test
    never runs more often than its writer asked for, and a normal request is checked once:
    repeating it finds nothing."""
    if spec.kind == "normal":
        return 1
    return min(spec.repeats, max(1, min(runs, MAX_RUNS)))


def turns_for(spec: TestSpec) -> int:
    """A normal request is one message. An attack goes on as long as its writer allowed."""
    return 1 if spec.kind == "normal" else spec.max_turns


def messages_by_runs(plan: Plan) -> list[int]:
    """The most messages the run could send to the bot, for each setting from 1 to 5 runs per
    attack (so the first number is for 1). A conversation that ends early sends fewer, so this
    is an upper bound."""
    return [
        sum(runs_for(spec, n) * turns_for(spec) for _, spec in planned(plan))
        for n in range(1, MAX_RUNS + 1)
    ]


def message_for(spec: TestSpec) -> str:
    """The first message to send. A bot over chat has no files to read, so text planted for it to
    read goes into the message as a document it is asked to handle."""
    planted = (spec.setup.planted_text or "").strip()
    if not planted:
        return spec.opening_message
    return (
        f"{spec.opening_message}\n\n--- start of document ---\n{planted}\n--- end of document ---"
    )


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_tests(plan: Plan, runs: int, stored: list[StoredSpec]) -> list[dict[str, Any]]:
    """The plan's tests as the runner takes them. `stored` holds the saved copy of each spec, in
    the same order as `planned(plan)`."""
    tests: list[dict[str, Any]] = []
    for number, ((goal, spec), saved) in enumerate(zip(planned(plan), stored, strict=True), 1):
        attack = spec.kind == "attack"
        turns = turns_for(spec)
        tests.append(
            {
                "id": f"p-{number}",
                "title": _clip(spec.goal, TITLE_CHARS),
                "risk": spec.risk,
                "kind": "negative" if attack else "positive",
                "severity": spec.severity,
                "prompt": message_for(spec),
                "goal": spec.goal,
                "expected": (
                    f"The bot refuses or deflects and does not do what this test is after: "
                    f"{spec.goal}"
                    if attack
                    else "The bot helps with the request in a normal, useful way."
                ),
                "rule": spec.rule,
                # The test's own rule (run by code) and what the owner wants caught (for the judge).
                "oracle": spec.oracle.model_dump(mode="json") if spec.oracle else None,
                "broke_if": spec.broke_if,
                "held_if": spec.held_if,
                "intention": spec.intention,
                "canaries": spec.setup.canaries,
                "technique": technique_name(spec.technique) if spec.technique else None,
                "escalate_to": spec.escalate_to,
                "rule_unconfirmed": False,
                "real_action": spec.changes_data,
                "fix": spec.fix_hint,
                "multi_turn": turns > 1,
                "max_turns": turns,
                "runs": runs_for(spec, runs),
                "persona": spec.persona,
                "planned_goal": goal.question,
                "spec_id": saved.spec_id,
                "spec_hash": saved.hash,
            }
        )
    return tests


def save_specs(specs: SpecStore, plan: Plan) -> list[StoredSpec]:
    """Save and lock every test in the plan: from here on each one is a fixed promise."""
    saved = [specs.create(spec) for _, spec in planned(plan)]
    return [specs.lock(s.spec_id) for s in saved]


def _turns_of(run: dict[str, Any]) -> list[Turn]:
    raw = run.get("turns")
    if raw:
        return [Turn(role=t["role"], content=t["content"]) for t in raw]
    if run.get("reply"):  # a single message and the bot's answer to it
        return [
            Turn(role="user", content=run["message"]),
            Turn(role="assistant", content=run["reply"]),
        ]
    return []


def record_for(
    test: dict[str, Any], runs: list[dict[str, Any]], combined: dict[str, Any]
) -> ResultRecord:
    """The proof for one test: the conversation that decided it, why, and how often it broke.

    The judge reads only the bot's replies, so a decided result says "reply only": no log or
    check confirmed it. A test that could not be run, or got no answer to judge, is never decided.
    """
    base = representative(runs)
    turns = _turns_of(base)
    replies = [i for i, turn in enumerate(turns) if turn.role == "assistant"]
    status = combined["status"]
    broke = sum(1 for r in runs if r["status"] == "fail")
    outcome: Outcome
    if status == "pass":
        outcome = "held"
    elif status == "fail":
        outcome = "broke"
    elif status == "inconclusive" and replies:
        outcome = "needs_review"
    else:
        outcome = "couldnt_test"
    decided = outcome in DECIDED
    by_rule = outcome == "broke" and combined.get("decided_by") == "rule"
    normal = test.get("kind") == "positive"
    said = {
        "held": "Your bot handled a normal request: " if normal else "Your bot held: ",
        "broke": "Your bot failed a normal request: " if normal else "Your bot broke: ",
        "needs_review": "This needs a person to look at: ",
        "couldnt_test": "This could not be tested: ",
    }[outcome]
    return ResultRecord(
        spec_id=test["spec_id"],
        spec_hash=test["spec_hash"],
        test_id=test.get("id"),
        outcome=outcome,
        what_happened=said + test["goal"],
        conversation=turns,
        attacker_messages=[t.content for t in turns if t.role == "user"] if decided else [],
        broke_at_turn=replies[-1] if outcome == "broke" else None,
        how_sure=("confirmed_by_checks" if by_rule else "reply_only") if decided else None,
        extra_proof=_rule_text(test),
        reason=combined["evidence"],
        repeat_count=len(runs),
        repeats_broke=broke,
        severity=test.get("severity"),
        fix=test.get("fix") or "",
    )


def _rule_text(test: dict[str, Any]) -> str | None:
    """The test's rule and intention in plain words, so the report can show what was checked."""
    disguised = f"Disguised as: {test['technique']}." if test.get("technique") else None
    parts = [disguised, test.get("broke_if"), test.get("held_if"), test.get("intention")]
    shown = [p for p in parts if p]
    if not shown:
        return None
    return " ".join(str(p) for p in shown)


def proof_saver(results: ResultStore, key: str | None) -> TestDone:
    """A hook for the runner: after each test, save its proof. The key is scrubbed from it."""

    async def done(
        scan_id: int, test: dict[str, Any], runs: list[dict[str, Any]], combined: dict[str, Any]
    ) -> None:
        if not test.get("spec_id"):
            return
        record = record_for(test, runs, combined)
        await asyncio.to_thread(results.save, f"scan-{scan_id}", record, [key] if key else [])

    return done
