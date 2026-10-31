"""Asking Redflag's own models for a small JSON answer, with a budget per role and per setup.

A bad answer is asked for once more, then reported as a clear failure. A used-up quota or a
failing provider is also a clear failure: there is no fallback to a different kind of model, and
nothing is saved when a call fails.
"""

import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from redflag_backend.llm.budget import BudgetBook
from redflag_backend.llm.router import Router, RouterFailure
from redflag_backend.llm.types import LLMRequest, Message

ATTEMPTS = 2
# Outcomes that mean a provider's per-minute quota is used up, so waiting a minute can help.
QUOTA_OUTCOMES = {"rate_limited", "cooling_down", "simulated_rate_limit"}


@dataclass(frozen=True)
class Patience:
    """Opt-in: when the models' quota runs out, wait and ask again instead of failing. Only a
    background job should use it, because a person watching a chat turn cannot wait a minute."""

    wait_seconds: float
    max_waits: int
    on_wait: Callable[[float, int, int], None] | None = None
    on_resume: Callable[[], None] | None = None


class ModelFailure(Exception):
    """The model step could not produce a usable answer. `kind` and `status` go to the user."""

    def __init__(self, kind: str, status: int) -> None:
        super().__init__(kind)
        self.kind = kind
        self.status = status


def parse_json_answer[M: BaseModel](text: str, answer_type: type[M]) -> M | None:
    body = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", body, flags=re.DOTALL)
    if fenced:
        body = fenced.group(1)
    try:
        return answer_type.model_validate(json.loads(body))
    except (ValueError, ValidationError):
        return None


class SetupLLM:
    def __init__(self, router: Router, book: BudgetBook) -> None:
        self._router = router
        self._book = book

    async def ask[M: BaseModel](
        self,
        setup_id: int,
        role: str,
        system: str,
        user: str,
        answer_type: type[M],
        patience: Patience | None = None,
    ) -> M:
        budget = self._book.session(f"setup-{setup_id}-{role}", None)
        request = LLMRequest(
            messages=(Message("system", system), Message("user", user)),
            temperature=0.0,
            max_output_tokens=2048,
        )
        waits = 0
        bad_answers = 0
        while bad_answers < ATTEMPTS:
            try:
                result = await self._router.complete(request, budget)
            except RouterFailure as failure:
                if failure.kind == "budget_exceeded":
                    raise ModelFailure("budget_exceeded", 429) from failure
                quota = failure.kind == "all_providers_failed" and any(
                    attempt.outcome in QUOTA_OUTCOMES for attempt in failure.attempts
                )
                if patience is not None and quota and waits < patience.max_waits:
                    waits += 1
                    # Nothing was answered, so the try is not held against the budget.
                    budget.requests_used = max(0, budget.requests_used - 1)
                    if patience.on_wait is not None:
                        patience.on_wait(patience.wait_seconds, waits, patience.max_waits)
                    await asyncio.sleep(patience.wait_seconds)
                    if patience.on_resume is not None:
                        patience.on_resume()
                    continue
                raise ModelFailure("model_unavailable", 503) from failure
            parsed = parse_json_answer(result.answer.text, answer_type)
            if parsed is not None:
                return parsed
            bad_answers += 1
        raise ModelFailure("bad_model_answer", 502)
