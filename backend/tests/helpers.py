"""Shared test support: a scripted fake provider and a client builder.

The outside model providers are the only thing faked in router tests.
"""

import asyncio
import os
from collections.abc import Callable, Sequence

from fastapi.testclient import TestClient

from redflag_backend.app import create_app
from redflag_backend.llm.provider import Provider
from redflag_backend.llm.types import LLMAnswer, LLMRequest, ModelUnavailable
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
