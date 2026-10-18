"""Shared test support: a scripted fake provider and a client builder.

The outside model providers are the only thing faked in router tests.
"""

import os
from collections.abc import Callable, Sequence

from fastapi.testclient import TestClient

from redflag_backend.app import create_app
from redflag_backend.llm.types import LLMAnswer, LLMRequest, ProviderError
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
        script: Sequence[LLMAnswer | ProviderError] | None = None,
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
        if isinstance(outcome, ProviderError):
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
    providers: Sequence[FakeProvider],
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
