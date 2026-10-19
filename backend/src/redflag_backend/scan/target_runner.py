"""Run generated tests against a real bot over HTTP and save each result as it finishes.

Rules this file keeps: an endpoint failure is an error result with its cause, never a pass, and
the judge is not asked about it; there is no plain-rules check for a real bot, so the AI judge's
verdict is the result, and a judge that cannot answer gives inconclusive, never a pass; a hard cap
limits the requests sent; and the key lives only inside the target object for the length of the
run. Nothing the bot says is edited, apart from the key being replaced if the bot echoes it.
"""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from redflag_backend.judge.judge import Judge, JudgeRequest, JudgeVerdict, ToolDescription
from redflag_backend.llm.budget import BudgetCaps, SessionBudget
from redflag_backend.scan.store import ScanStore
from redflag_backend.targets.http_target import HttpTarget, TargetResult

NO_RULE_NOTE = "No plain rule applies to a real bot, so the AI judge decided alone."
ENDPOINT_PROVIDER = "http"


def endpoint_label(host: str) -> str:
    return f"external endpoint ({host})"


@dataclass
class TargetScanRunner:
    store: ScanStore
    judge: Judge
    judge_caps: BudgetCaps
    clock: Callable[[], float]
    max_requests: int

    async def run(
        self,
        scan_id: int,
        tests: Sequence[dict[str, Any]],
        target: HttpTarget,
        judge_context: str,
        judge_tools: Sequence[ToolDescription],
        host: str,
    ) -> None:
        judge_budget = SessionBudget(self.judge_caps, started=self.clock())
        sent = 0
        try:
            for position, test in enumerate(tests):
                started = self.clock()
                if sent >= self.max_requests:
                    result = self._result(
                        position, test, started, "error",
                        f"Not run: the request cap of {self.max_requests} for one run was reached."
                    )  # fmt: skip
                else:
                    sent += 1
                    result = await self._one(
                        position,
                        test,
                        started,
                        target,
                        judge_context,
                        judge_tools,
                        judge_budget,
                        host,
                    )
                await asyncio.to_thread(self.store.add_result, scan_id, result, self.clock())
            await asyncio.to_thread(self.store.finish_scan, scan_id, "completed", self.clock())
        except Exception as error:  # a bug must not leave the scan looking "running" forever
            note = f"The run stopped because of an unexpected problem ({type(error).__name__})."
            await asyncio.to_thread(
                self.store.finish_scan, scan_id, "interrupted", self.clock(), note
            )

    async def _one(
        self,
        position: int,
        test: dict[str, Any],
        started: float,
        target: HttpTarget,
        judge_context: str,
        judge_tools: Sequence[ToolDescription],
        judge_budget: SessionBudget,
        host: str,
    ) -> dict[str, Any]:
        sent: TargetResult = await target.send(test["prompt"])
        if sent.status == "error":
            return self._result(position, test, started, "error", sent.error)
        rule = test.get("rule") or "The app's own rules, taken as a whole."
        at_stake = (
            f"{rule}\nWhat a correct reply looks like: {test['expected']}"
            if test["kind"] == "negative"
            else f"A normal request. What a correct reply looks like: {test['expected']}"
        )
        verdict: JudgeVerdict = await self.judge.judge(
            JudgeRequest(
                rule=at_stake,
                title=test["title"],
                kind=test["kind"],
                message=test["prompt"],
                reply=sent.reply,
                tool_calls=[],
                context=judge_context,
                tools=judge_tools,
            ),
            judge_budget,
        )
        status = {"pass": "pass", "fail": "fail"}.get(verdict.status, "inconclusive")
        reason = verdict.reason if verdict.reason.endswith(".") else f"{verdict.reason}."
        note = (
            NO_RULE_NOTE
            if verdict.status != "unavailable"
            else "No plain rule applies to a real bot, so this test is unclear."
        )
        return self._result(
            position,
            test,
            started,
            status,
            f"AI judge ({verdict.status.upper()}): {reason} {note}",
            reply=sent.reply,
            model=endpoint_label(host),
            provider=ENDPOINT_PROVIDER,
            judge_status=verdict.status,
            judge_reason=verdict.reason,
            judge_model=verdict.model,
            judge_provider=verdict.provider,
        )

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
