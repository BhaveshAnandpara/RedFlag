"""Run each attack against the weak and the hardened bot and keep what really happened.

The saved file is raw output: replies and tool logs are never edited. A run that cannot be
completed is saved as inconclusive, with the reason, instead of being left out or guessed.
"""

import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from redflag_backend.llm.budget import BudgetCaps, SessionBudget
from redflag_backend.llm.router import Attempt, Router, RouterFailure
from redflag_backend.llm.types import LLMRequest, Message
from redflag_backend.sandbox.attacks import ATTACKS, Attack
from redflag_backend.sandbox.bot import ALL_DEFENSES, TargetReply, build_bot
from redflag_backend.sandbox.checks import evaluate
from redflag_backend.sandbox.policy import Policy, default_policy

# Plenty for four attacks on two bots, each with a few tool steps, and still a hard limit.
RECORDING_CAPS = BudgetCaps(requests=200, tokens=400_000, seconds=1800.0, concurrency=1)
RETRIES = 1


class ToolRecord(BaseModel):
    tool: str
    arguments: dict[str, Any]
    outcome: str
    detail: str


class VerdictRecord(BaseModel):
    status: str
    evidence: str
    rule: str


class AttemptRecord(BaseModel):
    provider: str
    model: str | None
    outcome: str
    latency_ms: int


class Run(BaseModel):
    bot: str
    defenses: list[str]
    reply: str
    tool_calls: list[ToolRecord]
    verdict: VerdictRecord
    model: str | None
    provider: str | None
    attempts: list[AttemptRecord]
    recorded_at: str
    error: str | None


class AttackRecord(BaseModel):
    id: str
    title: str
    question: str
    message: str
    runs: dict[str, Run]


class Recordings(BaseModel):
    format_version: int = 1
    generated_at: str
    attacks: list[AttackRecord]


class RouterModel:
    """A bot's model, served by the router. Remembers who answered, for the recording."""

    def __init__(self, router: Router, budget: SessionBudget) -> None:
        self._router = router
        self._budget = budget
        self.model: str | None = None
        self.provider: str | None = None
        self.attempts: list[Attempt] = []

    async def __call__(self, messages: Sequence[Message]) -> str:
        # Headroom for reasoning models, which spend part of the budget thinking before they answer.
        request = LLMRequest(messages=tuple(messages), temperature=0.0, max_output_tokens=1024)
        try:
            result = await self._router.complete(request, self._budget)
        except RouterFailure as failure:
            self.attempts += failure.attempts
            raise
        self.model, self.provider = result.answer.model, result.provider
        self.attempts += result.attempts
        return result.answer.text


async def _run_once(
    router: Router,
    budget: SessionBudget,
    attack: Attack,
    bot_name: str,
    defenses: frozenset[str],
    policy: Policy,
    now: Callable[[], datetime],
) -> Run:
    error: str | None = None
    result: TargetReply | None = None
    model = RouterModel(router, budget)
    for _ in range(1 + RETRIES):
        model = RouterModel(router, budget)
        try:
            result = await build_bot(model, defenses).send(attack.message, attack.approvals)
            error = None
            break
        except RouterFailure as failure:
            error = f"model call failed: {failure.kind}"
    verdict = evaluate(attack.id, result, policy, attack.approvals, error)
    return Run(
        bot=bot_name,
        defenses=sorted(defenses),
        reply=result.reply if result else "",
        tool_calls=[
            ToolRecord(tool=c.tool, arguments=c.arguments, outcome=c.outcome, detail=c.detail)
            for c in (result.tool_calls if result else [])
        ],
        verdict=VerdictRecord(status=verdict.status, evidence=verdict.evidence, rule=verdict.rule),
        model=model.model,
        provider=model.provider,
        attempts=[
            AttemptRecord(
                provider=a.provider, model=a.model, outcome=a.outcome, latency_ms=a.latency_ms
            )
            for a in model.attempts
        ],
        recorded_at=now().isoformat(),
        error=error,
    )


async def record_all(
    router: Router, now: Callable[[], datetime] = lambda: datetime.now(UTC)
) -> Recordings:
    policy = default_policy()
    budget = SessionBudget(RECORDING_CAPS, started=time.time())
    attacks: list[AttackRecord] = []
    for attack in ATTACKS:
        runs = {
            "weak": await _run_once(router, budget, attack, "weak", frozenset(), policy, now),
            "hardened": await _run_once(
                router, budget, attack, "hardened", ALL_DEFENSES, policy, now
            ),
        }
        attacks.append(
            AttackRecord(
                id=attack.id,
                title=attack.title,
                question=attack.question,
                message=attack.message,
                runs=runs,
            )
        )
    return Recordings(generated_at=now().isoformat(), attacks=attacks)
