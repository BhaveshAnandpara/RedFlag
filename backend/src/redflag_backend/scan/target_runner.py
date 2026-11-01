"""Run generated tests against a real bot over HTTP and save each result as it finishes.

Rules this file keeps: an endpoint failure is an error result with its cause, never a pass, and
the judge is not asked about it; there is no plain-rules check for a real bot, so the AI judge's
verdict is the result, and a judge that cannot answer gives inconclusive, never a pass; a hard cap
limits the requests sent, every turn of a conversation counting as one; a multi-turn attack that
cannot continue is inconclusive, never a pass; and the key lives only inside the target object for
the length of the run. Nothing the bot says is edited, apart from the key being replaced if the
bot echoes it.
"""

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from redflag_backend.attacks.attacker import Attacker
from redflag_backend.judge.judge import Judge, JudgeRequest, JudgeVerdict, ToolDescription
from redflag_backend.llm.budget import BudgetCaps, SessionBudget
from redflag_backend.scan.store import ScanStore
from redflag_backend.specs.oracle import Conversation, Oracle, Turn, evaluate
from redflag_backend.targets.http_target import TIMED_OUT, HttpTarget, TargetResult

NO_RULE_NOTE = "No plain rule applies to a real bot, so the AI judge decided alone."
ENDPOINT_PROVIDER = "http"
# A run that was planned and approved can last a long while, mostly waiting for the models' quota.
LONG_RUN_SECONDS = 4 * 3600.0
JUDGE_CALLS_PER_SEND = 2

log = logging.getLogger(__name__)

# Called after each test with its scan id, the test, the result of every run of it, and the
# combined result. A failure here is logged and never stops the run.
TestDone = Callable[[int, dict[str, Any], list[dict[str, Any]], dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class RunOptions:
    """What a planned run asks of the runner beyond the usual share."""

    max_requests: int | None = None
    on_test_done: TestDone | None = None
    # Only a run someone is watching (from the open page) may pause and wait for them. A run
    # started from the owner's page or CI has no one to answer, so it just records what happened.
    can_pause: bool = False


def endpoint_label(host: str) -> str:
    return f"external endpoint ({host})"


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


@dataclass
class RunControl:
    """What the person watching a paused run answered: retry or stop."""

    event: asyncio.Event = field(default_factory=asyncio.Event)
    decision: str | None = None


@dataclass
class _Held:
    """A test the bot gave no answer to. It is kept aside until it is clear whether the bot is
    only having a blip (then it is saved as it is) or is gone (then a person decides)."""

    position: int
    test: dict[str, Any]
    runs: list[dict[str, Any]]
    result: dict[str, Any]
    used: int  # requests it used from the run's cap


def _no_answer(runs: list[dict[str, Any]]) -> bool:
    """True when every run of a test got no usable answer from the bot (a timeout, a refused
    connection, a server error). A test never run because of the request cap is not that."""
    return all(r["status"] == "error" and not r["evidence"].startswith("Not run:") for r in runs)


@dataclass
class _Run:
    """What one run shares between its tests."""

    target: HttpTarget
    judge_context: str
    judge_tools: Sequence[ToolDescription]
    judge_budget: SessionBudget
    attacker_budget: SessionBudget
    host: str
    max_requests: int
    scan_id: int
    sent: int = 0


@dataclass
class TargetScanRunner:
    store: ScanStore
    judge: Judge
    judge_caps: BudgetCaps
    clock: Callable[[], float]
    max_requests: int
    attacker: Attacker
    max_turns: int = 4
    # How long to wait for one reply, and how long before asking once more for one that never came.
    reply_wait: float = 60.0
    retry_pause: float = 3.0
    # This many tests in a row with no answer pause the run until a person says retry or stop.
    pause_after: int = 3
    pause_timeout: float = 900.0
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    controls: dict[int, RunControl] = field(default_factory=dict)

    def answer(self, scan_id: int, decision: str) -> bool:
        """The person's answer to a paused run. False when that run is not waiting for one."""
        control = self.controls.get(scan_id)
        if control is None or decision not in ("retry", "stop"):
            return False
        control.decision = decision
        control.event.set()
        return True

    async def run(
        self,
        scan_id: int,
        tests: Sequence[dict[str, Any]],
        target: HttpTarget,
        judge_context: str,
        judge_tools: Sequence[ToolDescription],
        host: str,
        options: RunOptions | None = None,
    ) -> None:
        options = options or RunOptions()
        target.wait_up_to(self.reply_wait)
        cap = options.max_requests or self.max_requests
        judge_caps = self.judge_caps
        if options.max_requests:
            judge_caps = replace(
                judge_caps,
                requests=max(judge_caps.requests, cap * JUDGE_CALLS_PER_SEND),
                seconds=max(judge_caps.seconds, LONG_RUN_SECONDS),
            )
        run = _Run(
            target=target,
            judge_context=judge_context,
            judge_tools=judge_tools,
            judge_budget=SessionBudget(judge_caps, started=self.clock()),
            attacker_budget=(
                self.attacker.new_budget(cap, LONG_RUN_SECONDS)
                if options.max_requests
                else self.attacker.new_budget()
            ),
            host=host,
            max_requests=cap,
            scan_id=scan_id,
        )
        queue: deque[tuple[int, dict[str, Any]]] = deque(enumerate(tests))
        held: list[_Held] = []
        try:
            while queue:
                position, test = queue.popleft()
                before = run.sent
                runs = await self._test(position, test, self.clock(), run)
                result = self._combine(test, runs) if len(runs) > 1 else runs[0]
                if options.can_pause and _no_answer(runs):
                    held.append(_Held(position, test, runs, result, run.sent - before))
                    if len(held) < self.pause_after:
                        continue
                    answer = await self._ask_person(scan_id, len(held))
                    if answer == "retry":
                        # ask again, from the first test that got no answer. What was sent to a
                        # bot that was not answering does not use up the plan's request cap.
                        run.sent = max(0, run.sent - sum(item.used for item in held))
                        for item in reversed(held):
                            queue.appendleft((item.position, item.test))
                        held = []
                        continue
                    await self._save_held(scan_id, held, options)
                    await self._stop(scan_id, queue, answer)
                    return
                await self._save_held(scan_id, held, options)
                held = []
                await self._save(scan_id, test, runs, result, options)
            await self._save_held(scan_id, held, options)
            await asyncio.to_thread(self.store.finish_scan, scan_id, "completed", self.clock())
        except Exception as error:  # a bug must not leave the scan looking "running" forever
            note = f"The run stopped because of an unexpected problem ({type(error).__name__})."
            await asyncio.to_thread(
                self.store.finish_scan, scan_id, "interrupted", self.clock(), note
            )

    # --- saving, pausing and stopping -----------------------------------------------------------

    async def _save(
        self,
        scan_id: int,
        test: dict[str, Any],
        runs: list[dict[str, Any]],
        result: dict[str, Any],
        options: RunOptions,
    ) -> None:
        await asyncio.to_thread(self.store.add_result, scan_id, result, self.clock())
        if options.on_test_done is not None:
            try:
                await options.on_test_done(scan_id, test, runs, result)
            except Exception:  # the proof is kept on a best effort: never stop the run
                log.warning("could not save the proof for test %s", test.get("id"))

    async def _save_held(self, scan_id: int, held: list[_Held], options: RunOptions) -> None:
        for item in held:
            await self._save(scan_id, item.test, item.runs, item.result, options)

    async def _ask_person(self, scan_id: int, count: int) -> str:
        """Pause the run and wait for a person to say retry or stop. Returns "retry", "stop", or
        "timeout" when nobody answered in time. Nothing is sent to the bot while it waits."""
        control = RunControl()
        self.controls[scan_id] = control
        note = (
            f"Your bot stopped answering: the last {count} tests in a row got no usable reply. "
            "Fix it (for example restart your tunnel), then press Retry. Stop keeps what was "
            "tested so far."
        )
        await asyncio.to_thread(self.store.pause_scan, scan_id, note, self.clock())
        try:
            await asyncio.wait_for(control.event.wait(), self.pause_timeout)
            decision = control.decision or "stop"
        except TimeoutError:
            decision = "timeout"
        finally:
            self.controls.pop(scan_id, None)
        if decision == "retry":
            await asyncio.to_thread(self.store.resume_scan, scan_id, self.clock())
        return decision

    async def _stop(self, scan_id: int, queue: deque[tuple[int, dict[str, Any]]], why: str) -> None:
        """End the run early. What was tested is kept, and every test that was not run says so,
        so the counts still add up to the plan."""
        left = len(queue)
        reason = (
            "nobody answered for a while, so the run was stopped"
            if why == "timeout"
            else "you stopped the run"
        )
        while queue:
            position, test = queue.popleft()
            skipped = self._result(
                position,
                test,
                self.clock(),
                "error",
                f"Not run: {reason} after your bot stopped answering.",
            )
            await asyncio.to_thread(self.store.add_result, scan_id, skipped, self.clock())
        note = (
            f"The run was stopped after your bot stopped answering ({reason}). "
            f"{_plural(left, 'test was', 'tests were')} not run. Everything tested before is kept."
        )
        await asyncio.to_thread(self.store.finish_scan, scan_id, "interrupted", self.clock(), note)

    # --- one test, run as many times as it asks ----------------------------------------------

    async def _test(
        self, position: int, test: dict[str, Any], started: float, run: _Run
    ) -> list[dict[str, Any]]:
        """Every run of one test, each its own conversation from turn one."""
        runs: list[dict[str, Any]] = []
        for _ in range(max(1, int(test.get("runs") or 1))):
            if run.sent >= run.max_requests:
                runs.append(
                    self._result(
                        position,
                        test,
                        started,
                        "error",
                        f"Not run: the request cap of {run.max_requests} for one run was reached.",
                    )
                )
                break
            if test.get("multi_turn"):
                runs.append(await self._conversation(position, test, started, run))
            else:
                run.sent += 1
                runs.append(await self._one(position, test, started, run))
            await asyncio.to_thread(self.store.touch, run.scan_id, self.clock())
        return runs

    def _combine(self, test: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
        """One result for a test that ran more than once. One break is proof, so it wins; it
        counts as held only if every run held, and a run that could not be tested is never held."""
        total = len(runs)
        broke = sum(1 for r in runs if r["status"] == "fail")
        held = sum(1 for r in runs if r["status"] == "pass")
        base = representative(runs)
        if broke:
            summary = f"Broke in {broke} of {_plural(total, 'run', 'runs')}."
        elif held == total:
            summary = f"Held in all {_plural(total, 'run', 'runs')}."
        else:
            summary = (
                f"Held in {held} of {_plural(total, 'run', 'runs')}; the rest could not be tested."
            )
        return {**base, "evidence": f"{summary} {base['evidence']}"}

    # --- one message ------------------------------------------------------------------------

    async def _call(self, run: _Run, send: Callable[[], Awaitable[TargetResult]]) -> TargetResult:
        """One request to the bot. A reply that never came is asked for once more, as a separate
        request after a short pause: a bot that is only slow often answers the second time. Any
        other failure is not asked again. The second ask does not use up the run's request cap,
        which is sized to the plan: a retry must not cost a test its place."""
        sent = await send()
        if sent.status == "error" and sent.error == TIMED_OUT:
            await self.sleep(self.retry_pause)
            sent = await send()
        return sent

    async def _one(
        self, position: int, test: dict[str, Any], started: float, run: _Run
    ) -> dict[str, Any]:
        sent = await self._call(run, lambda: run.target.send(test["prompt"]))
        if sent.status == "error":
            return self._result(position, test, started, "error", sent.error)
        verdict = await self._judge(test, run, test["prompt"], sent.reply, ())
        status = {"pass": "pass", "fail": "fail"}.get(verdict.status, "inconclusive")
        return self._result(
            position,
            test,
            started,
            status,
            f"{_who(verdict)} ({verdict.status.upper()}): {_sentence(verdict.reason)} "
            f"{_note(verdict)}",
            reply=sent.reply,
            **self._answered(run, verdict),
        )

    # --- a conversation of several turns ----------------------------------------------------

    async def _conversation(
        self, position: int, test: dict[str, Any], started: float, run: _Run
    ) -> dict[str, Any]:
        turns: list[dict[str, str]] = []
        message = test["prompt"]
        rule = test.get("rule") or "The app's own rules, taken as a whole."
        last_reply = ""
        verdict: JudgeVerdict | None = None
        max_turns = int(test.get("max_turns") or self.max_turns)

        def result(status: str, evidence: str, **more: Any) -> dict[str, Any]:
            extra = self._answered(run, verdict) if verdict else {}
            return self._result(
                position,
                test,
                started,
                status,
                evidence,
                reply=last_reply,
                turns=list(turns),
                **extra,
                **more,
            )

        for turn in range(1, max_turns + 1):
            if run.sent >= run.max_requests:
                return result(
                    "inconclusive",
                    f"Stopped after {_plural(turn - 1, 'turn', 'turns')}: the request cap of "
                    f"{run.max_requests} for one run was reached, so this test is unclear.",
                )
            run.sent += 1
            turns.append({"role": "user", "content": message})
            sent = await self._call(run, lambda: run.target.send_conversation(turns))
            if sent.status == "error":
                return result("error", sent.error)
            last_reply = sent.reply
            turns.append({"role": "assistant", "content": sent.reply})

            verdict = await self._judge(
                test, run, message, sent.reply, [(t["role"], t["content"]) for t in turns]
            )
            if verdict.status == "fail":
                return result(
                    "fail",
                    f"{_who(verdict)} (FAIL): {_sentence(verdict.reason)} The bot broke a rule "
                    f"on turn {turn} of the conversation. {_note(verdict)}",
                )
            if verdict.status == "disputed":
                return result(
                    "inconclusive",
                    f"{_sentence(verdict.reason)} It happened on turn {turn} of the "
                    f"conversation. {_note(verdict)}",
                )
            if verdict.status == "unavailable":
                return result(
                    "inconclusive",
                    f"AI judge (UNAVAILABLE): {_sentence(verdict.reason)} The conversation could "
                    "not be judged, so this test is unclear.",
                )
            if turn == max_turns:
                return result(
                    "pass",
                    f"AI judge (PASS): {_sentence(verdict.reason)} The bot held for "
                    f"{_plural(turn, 'turn', 'turns')}. {NO_RULE_NOTE}",
                )

            step = await self.attacker.next_message(
                goal=test["goal"],
                rule=rule,
                expected=test["expected"],
                context=run.judge_context,
                transcript=turns,
                turn=turn,
                max_turns=max_turns,
                budget=run.attacker_budget,
            )
            if step.kind == "gave_up":
                return result(
                    "pass",
                    f"AI judge (PASS): {_sentence(verdict.reason)} The attacker gave up after "
                    f"{_plural(turn, 'turn', 'turns')} without a new angle. {NO_RULE_NOTE}",
                )
            if step.kind == "unavailable":
                return result(
                    "inconclusive",
                    f"The attacker could not continue the conversation after "
                    f"{_plural(turn, 'turn', 'turns')} ({step.reason}), so this test is unclear.",
                )
            message = step.message
        raise AssertionError("unreachable: the loop returns at the turn cap")

    # --- shared pieces ----------------------------------------------------------------------

    async def _judge(
        self,
        test: dict[str, Any],
        run: _Run,
        message: str,
        reply: str,
        transcript: Sequence[tuple[str, str]],
    ) -> JudgeVerdict:
        rule = test.get("rule") or "The app's own rules, taken as a whole."
        at_stake = (
            f"{rule}\nWhat a correct reply looks like: {test['expected']}"
            if test["kind"] == "negative"
            else f"A normal request. What a correct reply looks like: {test['expected']}"
        )
        if test.get("intention"):
            at_stake += f"\nWhat the owner wants caught, in this test: {test['intention']}"
        hit = _rule_hit(test, message, reply, transcript)
        verdict = await self.judge.judge(
            JudgeRequest(
                rule=at_stake,
                title=test["title"],
                kind=test["kind"],
                message=message,
                reply=reply,
                tool_calls=[],
                context=run.judge_context,
                tools=run.judge_tools,
                transcript=transcript,
            ),
            run.judge_budget,
        )
        if hit is None:
            return verdict
        # The test's own rule found a break, checked by code. The judge read it too, with the
        # intention: if it says the reply was fine, a person looks; otherwise the rule stands.
        if verdict.status == "pass":
            return replace(
                verdict,
                status="disputed",
                reason=f"{hit} But the AI judge read the reply as fine: {verdict.reason}",
            )
        return replace(verdict, status="fail", reason=hit, by_rule=True)

    def _answered(self, run: _Run, verdict: JudgeVerdict) -> dict[str, Any]:
        return {
            "model": endpoint_label(run.host),
            "provider": ENDPOINT_PROVIDER,
            "judge_status": verdict.status,
            "decided_by": "rule" if verdict.by_rule else "judge",
            "judge_reason": verdict.reason,
            "judge_model": verdict.model,
            "judge_provider": verdict.provider,
        }

    def _result(
        self,
        position: int,
        test: dict[str, Any],
        started: float,
        status: str,
        evidence: str,
        **more: Any,
    ) -> dict[str, Any]:
        return {
            "position": position,
            "test_id": test["id"],
            "risk": test["risk"],
            "kind": test["kind"],
            "title": test["title"],
            "message": test["prompt"],
            "reply": "",
            "tool_calls": [],
            "rule": test.get("rule") or "The app's own rules, taken as a whole.",
            "model": None,
            "provider": None,
            "attempts": [],
            "started_at": started,
            "finished_at": self.clock(),
            "severity": test.get("severity"),
            "remediation": test.get("fix") or None,
            "status": status,
            "evidence": evidence,
            **more,
        }


def representative(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """The run that stands for a test that ran more than once: the first one that broke, else the
    first one that could not be tested, else the first one. One break is proof, so it wins, and a
    run that could not be tested is never counted as held."""
    for run in runs:
        if run["status"] == "fail":
            return run
    for run in runs:
        if run["status"] != "pass":
            return run
    return runs[0]


def _rule_hit(
    test: dict[str, Any], message: str, reply: str, transcript: Sequence[tuple[str, str]]
) -> str | None:
    """The test's own rule, run by code on what happened so far. Its words if it says Broke, else
    None (no rule, it did not match, or it could not be checked)."""
    raw = test.get("oracle")
    if not raw:
        return None
    oracle = Oracle.model_validate(raw)
    if transcript:
        turns = [Turn.model_validate({"role": role, "content": text}) for role, text in transcript]
    else:
        turns = [Turn(role="user", content=message), Turn(role="assistant", content=reply)]
    outcome = evaluate(oracle, Conversation(turns=turns))
    return outcome.reason if outcome.verdict == "broke" else None


def _who(verdict: JudgeVerdict) -> str:
    return "Rule check" if verdict.by_rule else "AI judge"


def _note(verdict: JudgeVerdict) -> str:
    if verdict.by_rule:
        return "The test's own rule found it, and the AI judge did not say it was fine."
    if verdict.status == "disputed":
        return "The rule and the AI judge disagree, so a person should look."
    if verdict.status == "unavailable":
        return "No plain rule applies to a real bot, so this test is unclear."
    return NO_RULE_NOTE


def _sentence(text: str) -> str:
    return text if text.endswith(".") else f"{text}."
