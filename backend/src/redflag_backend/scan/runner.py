"""Run a suite against one bot and save every result as it finishes.

Rules this file keeps: a model failure is retried once and then saved as an error, never a pass;
a budget stop saves the tests that did not run as errors with the reason, not as skipped; a test
the bot cannot run is "not applicable", never "tested". Nothing the bot says is edited.
"""

import asyncio
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from redflag_backend.llm.budget import BudgetCaps, SessionBudget
from redflag_backend.llm.router import Router, RouterFailure
from redflag_backend.sandbox.bot import TargetReply
from redflag_backend.sandbox.loader import BotDefinition
from redflag_backend.sandbox.recording import RouterModel
from redflag_backend.scan.catalog import Catalog
from redflag_backend.scan.checks import CheckContext, evaluate, missing_needs
from redflag_backend.scan.store import ScanStore
from redflag_backend.scan.suite import ScanTest, Suite

RETRIES = 1


def new_canary() -> str:
    """A fresh fake secret for one scan, so a leak is unmistakable and never a lucky match."""
    return f"CANARY-{secrets.token_hex(6)}"


@dataclass
class ScanRunner:
    store: ScanStore
    router: Router
    caps: BudgetCaps
    clock: Callable[[], float]
    suite: Suite
    catalog: Catalog

    def scan_settings(
        self, definition: BotDefinition, canary: str, provider_names: list[str]
    ) -> dict[str, Any]:
        return {
            "bot_id": definition.config.id,
            "bot_name": definition.config.name,
            "bot_config_version": definition.config.config_version,
            "bot_defenses": sorted(definition.defenses),
            "catalog_version": self.catalog.version,
            "suite_version": self.suite.suite_version,
            "test_count": len(self.suite.tests),
            "canary": canary,
            "providers": provider_names,
            "budget": {
                "requests": self.caps.requests,
                "tokens": self.caps.tokens,
                "seconds": self.caps.seconds,
                "concurrency": self.caps.concurrency,
            },
        }

    async def run(self, scan_id: int, definition: BotDefinition, canary: str) -> None:
        budget = SessionBudget(self.caps, started=self.clock())
        stopped: str | None = None
        try:
            for position, test in enumerate(self.suite.tests):
                result, stopped = await self._run_test(
                    position, test, definition, canary, budget, stopped
                )
                await asyncio.to_thread(self.store.add_result, scan_id, result, self.clock())
            await asyncio.to_thread(self.store.finish_scan, scan_id, "completed", self.clock())
        except Exception as error:  # a bug must not leave the scan looking "running" forever
            note = f"The scan stopped because of an unexpected problem ({type(error).__name__})."
            await asyncio.to_thread(
                self.store.finish_scan, scan_id, "interrupted", self.clock(), note
            )

    async def _run_test(
        self,
        position: int,
        test: ScanTest,
        definition: BotDefinition,
        canary: str,
        budget: SessionBudget,
        stopped: str | None,
    ) -> tuple[dict[str, Any], str | None]:
        started = self.clock()
        rule = definition.policy.rules.get(test.rule, test.rule)
        base: dict[str, Any] = {
            "position": position,
            "test_id": test.id,
            "risk": test.risk,
            "kind": test.kind,
            "title": test.title,
            "message": test.message,
            "reply": "",
            "tool_calls": [],
            "rule": rule,
            "model": None,
            "provider": None,
            "attempts": [],
            "started_at": started,
        }

        def done(status: str, evidence: str, **more: Any) -> dict[str, Any]:
            return {
                **base,
                "status": status,
                "evidence": evidence,
                "finished_at": self.clock(),
                **more,
            }

        missing = missing_needs(test, set(definition.tools), definition.data)
        if missing:
            return done("not_applicable", "This bot lacks: " + ", ".join(missing)), stopped
        if stopped:
            return done("error", f"Not run: the scan stopped early ({stopped})."), stopped

        failure = "model call failed"
        model = RouterModel(self.router, budget)
        for _ in range(1 + RETRIES):
            model = RouterModel(self.router, budget)
            bot = definition.create(model, secret=canary)
            try:
                reply = await bot.send(test.message, test.approvals)
            except RouterFailure as router_failure:
                if router_failure.kind == "budget_exceeded":
                    stopped = f"budget cap reached: {router_failure.cap}"
                    return done("error", f"Not run: the bots' {stopped}.", **_notes(model)), stopped
                failure = f"model call failed: {router_failure.kind}"
                continue
            except Exception as error:  # logged by type only, never the message
                return done("error", f"Unexpected error: {type(error).__name__}"), stopped
            return self._judged(done, test, reply, definition, canary, bot.prompt, model), stopped
        return done("error", failure, **_notes(model)), stopped

    def _judged(
        self,
        done: Callable[..., dict[str, Any]],
        test: ScanTest,
        reply: TargetReply,
        definition: BotDefinition,
        canary: str,
        prompt: str,
        model: RouterModel,
    ) -> dict[str, Any]:
        ctx = CheckContext(
            data={**definition.data, "secret": canary},
            policy=definition.policy,
            prompt=prompt,
            secret=canary,
        )
        verdict = evaluate(test, reply, ctx)
        return done(
            verdict.status,
            verdict.evidence,
            reply=reply.reply,
            tool_calls=[
                {"tool": c.tool, "arguments": c.arguments, "outcome": c.outcome, "detail": c.detail}
                for c in reply.tool_calls
            ],
            rule=verdict.rule,
            **_notes(model),
        )


def _notes(model: RouterModel) -> dict[str, Any]:
    return {
        "model": model.model,
        "provider": model.provider,
        "attempts": [
            {
                "provider": a.provider,
                "model": a.model,
                "outcome": a.outcome,
                "latency_ms": a.latency_ms,
            }
            for a in model.attempts
        ],
    }
