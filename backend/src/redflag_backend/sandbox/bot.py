"""The bot runtime and the target interface: send a message, get a reply and a tool log.

What a bot is (its prompt, data, policy, tools and defenses) comes from its folder under
backend/bots; this file only runs it.
"""

import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from redflag_backend.llm.types import Message
from redflag_backend.sandbox.policy import Policy
from redflag_backend.sandbox.tools import ToolBox, ToolCall

# The router has no native tool calling, so a bot asks for a tool in plain text. The format is
# deliberately not "TOOL_CALL ...": some models (gpt-oss on Groq) read that as their own built-in
# tool calling, and the provider then rejects the request.
TOOL_CALL = re.compile(r"^\[\[(\w+) (.*)\]\]\s*$", re.MULTILINE)
MAX_STEPS = 4

Model = Callable[[Sequence[Message]], Awaitable[str]]

# The defenses a bot's config may switch on. All are enforced in code by the tools or by the
# reply filter, so the model cannot be talked out of them. Prompt wording is just the bot's prompt.
ALL_DEFENSES = frozenset(
    {"secret_protection", "order_scoping", "refund_approval", "document_isolation"}
)

REFUSED_REPLY = "Sorry, I can't share that."


@dataclass(frozen=True)
class TargetReply:
    reply: str
    tool_calls: list[ToolCall]


class Bot:
    def __init__(
        self,
        model: Model,
        defenses: frozenset[str],
        prompt: str,
        data: dict[str, Any],
        policy: Policy,
        tools: Mapping[str, Callable[[ToolBox, dict[str, Any]], str]],
    ) -> None:
        self._model = model
        self._defenses = defenses
        self._data = data
        self._policy = policy
        self._tools = tools
        # The secret is filled in from the bot's data, so the prompt file never holds it.
        self.prompt = prompt.replace("{secret}", str(data.get("secret", "")))

    async def send(self, message: str, approvals: Sequence[str] = ()) -> TargetReply:
        tools = ToolBox(
            tools=self._tools,
            data=self._data,
            policy=self._policy,
            defenses=self._defenses,
            approvals=frozenset(approvals),
        )
        messages = [Message("system", self.prompt), Message("user", message)]
        for _ in range(MAX_STEPS):
            text = await self._model(messages)
            match = TOOL_CALL.search(text)
            if match is None:
                return TargetReply(self._filter(text), tools.calls)
            tool, raw = match.group(1), match.group(2)
            try:
                arguments = json.loads(raw)
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must be an object")
            except ValueError:
                tools.run("__malformed__", {"raw": raw})
                result = "That tool call was refused."
            else:
                result = tools.run(tool, arguments)
            messages += [Message("assistant", text), Message("user", f"RESULT {result}")]
        # The model never produced an answer. Say so instead of inventing one.
        return TargetReply("", tools.calls)

    def _filter(self, reply: str) -> str:
        secret = str(self._data.get("secret", ""))
        if "secret_protection" in self._defenses and secret and secret in reply:
            return REFUSED_REPLY
        return reply
