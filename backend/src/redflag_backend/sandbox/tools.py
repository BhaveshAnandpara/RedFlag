"""Tool runtime: the log, the dispatch, and the context a bot's own tool code runs in.

The tools themselves live in the bot's folder (see backend/bots). This file only runs them and
writes the tool-call log, so every call is recorded the same way for every bot.
"""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from redflag_backend.sandbox.policy import Policy


@dataclass(frozen=True)
class ToolCall:
    """One line of the tool-call log."""

    tool: str
    arguments: dict[str, Any]
    outcome: str  # executed | blocked | refused
    detail: str
    at: float


@dataclass
class ToolBox:
    """What a bot's tool code sees for one turn: the data, the rules, the switches, the log."""

    tools: Mapping[str, Callable[["ToolBox", dict[str, Any]], str]]
    data: dict[str, Any]
    policy: Policy
    defenses: frozenset[str] = frozenset()
    approvals: frozenset[str] = frozenset()
    calls: list[ToolCall] = field(default_factory=list)
    # Scratch space for tools to remember things within one turn (such as "a document was read").
    state: dict[str, Any] = field(default_factory=dict)

    def run(self, tool: str, arguments: dict[str, Any]) -> str:
        handler = self.tools.get(tool)
        if handler is None:
            return self.log(tool, arguments, "refused", f"unknown tool: {tool}")
        try:
            return str(handler(self, arguments))
        except (KeyError, TypeError, ValueError) as error:
            return self.log(tool, arguments, "refused", f"bad arguments: {error!r}")

    def log(self, tool: str, arguments: dict[str, Any], outcome: str, detail: str) -> str:
        self.calls.append(ToolCall(tool, arguments, outcome, detail, time.time()))
        return detail
