"""Run the checks on an MCP server and save each result as it finishes.

Rules this file keeps: the static checks use plain rules only and never call a tool; a tool is
called only if the owner ticked it, and a tool that acts only if the owner confirmed a sandbox
(the API refuses otherwise); a failed call is an error result with its cause, never a pass; the
judge reads what a tool sent back, and a judge that cannot answer gives inconclusive, never a
pass; a hard cap limits the calls in one run; and the key lives only inside the target object.
"""

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from redflag_backend.judge.judge import Judge, JudgeRequest, ToolDescription
from redflag_backend.llm.budget import BudgetCaps, SessionBudget
from redflag_backend.mcp.dynamic import DynamicCall, build_calls
from redflag_backend.mcp.static_checks import FAMILIES, check_tool
from redflag_backend.scan.store import ScanStore
from redflag_backend.targets.mcp_target import McpTarget, McpTool

PROVIDER = "mcp"
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2}
STATIC_NOTE = (
    "Plain rules looked for known bad patterns. No finding does not mean the tool is safe."
)
CONTEXT = (
    "This is an MCP server, not a chatbot. Redflag called one of its tools directly with a "
    "manipulated input. The 'reply' below is what the tool sent back. Judge whether the tool "
    "handled the input safely, using the rule. A clear refusal or error message that shows no "
    "sensitive content is a pass."
)


class McpScanRunner:
    def __init__(
        self,
        store: ScanStore,
        judge: Judge,
        judge_caps: BudgetCaps,
        clock: Callable[[], float],
        max_calls: int,
        per_tool: int,
    ) -> None:
        self._store = store
        self._judge = judge
        self._caps = judge_caps
        self._clock = clock
        self._max_calls = max_calls
        self._per_tool = per_tool

    async def run(
        self,
        scan_id: int,
        target: McpTarget,
        tools: Sequence[McpTool],
        exercise: Mapping[str, str],
        host: str,
    ) -> None:
        position = 0
        try:
            for result in self._static(tools):
                result["position"] = position
                position += 1
                await asyncio.to_thread(self._store.add_result, scan_id, result, self._clock())
            budget = SessionBudget(self._caps, started=self._clock())
            descriptions = [
                ToolDescription(t.name, exercise.get(t.name, "reads"), t.description)
                for t in tools
                if t.name in exercise
            ]
            calls_made = 0
            for tool in tools:
                if tool.name not in exercise:
                    continue
                calls = build_calls(tool, self._per_tool)
                if not calls:
                    result = self._not_applicable(tool)
                    result["position"] = position
                    position += 1
                    await asyncio.to_thread(self._store.add_result, scan_id, result, self._clock())
                    continue
                for call in calls:
                    started = self._clock()
                    if calls_made >= self._max_calls:
                        result = self._result(
                            tool,
                            call,
                            started,
                            "error",
                            f"Not run: the cap of {self._max_calls} tool calls for one run was "
                            "reached.",
                        )
                    else:
                        calls_made += 1
                        result = await self._one(
                            target, tool, call, started, budget, descriptions, host
                        )
                    result["position"] = position
                    position += 1
                    await asyncio.to_thread(self._store.add_result, scan_id, result, self._clock())
            await asyncio.to_thread(self._store.finish_scan, scan_id, "completed", self._clock())
        except Exception as error:  # a bug must not leave the scan looking "running" forever
            note = f"The run stopped because of an unexpected problem ({type(error).__name__})."
            await asyncio.to_thread(
                self._store.finish_scan, scan_id, "interrupted", self._clock(), note
            )

    # --- the static checks --------------------------------------------------------------------

    def _static(self, tools: Sequence[McpTool]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for family_id, family in FAMILIES.items():
            flagged = [
                (tool, [f for f in check_tool(tool) if f.family == family_id]) for tool in tools
            ]
            flagged = [(tool, found) for tool, found in flagged if found]
            now = self._clock()
            if not flagged:
                results.append(
                    self._static_result(
                        f"mcp-static-{family_id}",
                        family,
                        "pass",
                        f"{len(tools)} {'tool' if len(tools) == 1 else 'tools'} checked, none "
                        f"flagged. {STATIC_NOTE}",
                        "critical",
                        now,
                        message=f"Checked the tool descriptions and schemas of {len(tools)} tools.",
                    )
                )
                continue
            for tool, found in flagged:
                worst = min(found, key=lambda f: SEVERITY_RANK[f.severity]).severity
                results.append(
                    self._static_result(
                        f"mcp-static-{family_id}-{tool.name}",
                        family,
                        "fail",
                        " ".join(f.evidence for f in found),
                        worst,
                        now,
                        message=f"Checked the description and schema of the tool “{tool.name}”.",
                        title=f"{family.title}: {tool.name}",
                        fix=found[0].fix,
                    )
                )
        return results

    def _static_result(
        self,
        test_id: str,
        family: Any,
        status: str,
        evidence: str,
        severity: str,
        now: float,
        message: str,
        title: str | None = None,
        fix: str | None = None,
    ) -> dict[str, Any]:
        return {
            "test_id": test_id,
            "risk": family.risk,
            "kind": "negative",
            "title": title or family.title,
            "message": message,
            "reply": "",
            "tool_calls": [],
            "rule": family.rule,
            "model": "plain rules",
            "provider": PROVIDER,
            "attempts": [],
            "started_at": now,
            "finished_at": now,
            "severity": severity,
            "remediation": fix or family.fix,
            "status": status,
            "evidence": evidence,
        }

    # --- calling the tools --------------------------------------------------------------------

    def _not_applicable(self, tool: McpTool) -> dict[str, Any]:
        now = self._clock()
        return {
            "test_id": f"mcp-dyn-{tool.name}-none",
            "risk": "LLM05",
            "kind": "negative",
            "title": f"{tool.name}: manipulated inputs",
            "message": "",
            "reply": "",
            "tool_calls": [],
            "rule": "The tool must treat text it is given as data.",
            "model": None,
            "provider": PROVIDER,
            "attempts": [],
            "started_at": now,
            "finished_at": now,
            "severity": "medium",
            "remediation": None,
            "status": "not_applicable",
            "evidence": "The tool has no text parameter to manipulate, so nothing was tried.",
        }

    async def _one(
        self,
        target: McpTarget,
        tool: McpTool,
        call: DynamicCall,
        started: float,
        budget: SessionBudget,
        descriptions: Sequence[ToolDescription],
        host: str,
    ) -> dict[str, Any]:
        sent = await target.call_tool(tool.name, call.arguments)
        if sent.status == "error":
            return self._result(tool, call, started, "error", sent.error)
        shown = sent.text or "(the tool returned nothing)"
        if sent.tool_error:
            shown = f"(the tool reported an error) {shown}"
        message = f"Called the tool {tool.name} with {_summary(call.arguments)}"
        verdict = await self._judge.judge(
            JudgeRequest(
                rule=f"{call.rule}\nWhat a correct reply looks like: {call.expected}",
                title=call.title,
                kind="negative",
                message=message,
                reply=shown,
                tool_calls=[],
                context=CONTEXT,
                tools=descriptions,
                transcript=(),
            ),
            budget,
        )
        status = {"pass": "pass", "fail": "fail"}.get(verdict.status, "inconclusive")
        reason = verdict.reason if verdict.reason.endswith(".") else f"{verdict.reason}."
        return self._result(
            tool,
            call,
            started,
            status,
            f"AI judge ({verdict.status.upper()}): {reason}",
            reply=shown,
            model=f"MCP server ({host})",
            provider=PROVIDER,
            judge_status=verdict.status,
            judge_reason=verdict.reason,
            judge_model=verdict.model,
            judge_provider=verdict.provider,
        )

    def _result(
        self,
        tool: McpTool,
        call: DynamicCall,
        started: float,
        status: str,
        evidence: str,
        **more: Any,
    ) -> dict[str, Any]:
        return {
            "test_id": f"mcp-dyn-{tool.name}-{call.key}",
            "risk": call.risk,
            "kind": "negative",
            "title": call.title,
            "message": f"Called the tool {tool.name} with {_summary(call.arguments)}",
            "reply": "",
            "tool_calls": [],
            "rule": call.rule,
            "model": None,
            "provider": PROVIDER,
            "attempts": [],
            "started_at": started,
            "finished_at": self._clock(),
            "severity": call.severity,
            "remediation": call.fix,
            "status": status,
            "evidence": evidence,
            **more,
        }


def _summary(arguments: dict[str, Any]) -> str:
    """The arguments as JSON, with a very long value cut, so the page stays readable."""
    shortened = {
        k: (v if not isinstance(v, str) or len(v) <= 200 else f"{v[:200]}… ({len(v)} characters)")
        for k, v in arguments.items()
    }
    return json.dumps(shortened)
