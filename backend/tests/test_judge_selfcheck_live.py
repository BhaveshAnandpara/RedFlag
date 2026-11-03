"""The judge's own check against Redflag's real models: catches a prompt change that made the
judge worse. Costs a few model calls, so it only runs when asked (REDFLAG_LIVE_JUDGE_CHECK=1) and
a key is configured; in CI it is skipped until a key is added as a secret and that variable set."""

import asyncio
import os
import time

import pytest

from redflag_backend.judge.judge import Judge
from redflag_backend.judge.selfcheck import run_self_check
from redflag_backend.llm.budget import BudgetCaps, SessionBudget
from redflag_backend.llm.providers.factory import build_providers
from redflag_backend.llm.router import Router
from redflag_backend.settings import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("REDFLAG_LIVE_JUDGE_CHECK") != "1",
    reason="set REDFLAG_LIVE_JUDGE_CHECK=1 (and a model key) to check the real judge",
)


def test_the_real_judge_passes_its_own_check() -> None:
    providers = [p for p in build_providers(Settings()) if p.configured]
    if not providers:
        pytest.skip("no model key is configured")
    judge = Judge(Router(providers, clock=time.monotonic), clock=time.monotonic)
    caps = BudgetCaps(requests=30, tokens=100_000, seconds=600.0, concurrency=1)
    result = asyncio.run(run_self_check(judge, SessionBudget(caps, started=time.monotonic())))
    assert result.unavailable == 0, "the judge could not answer (quota?), so nothing was checked"
    assert result.passed == result.total, f"the judge passed {result.passed} of {result.total}"
