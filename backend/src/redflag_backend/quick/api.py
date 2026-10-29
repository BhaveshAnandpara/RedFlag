"""The quick scan: a hello check, and one call that sets a bot up and runs the starter pack.

Open to anyone (no owner password). There is no select step: the pack is fixed, so
nothing needs choosing. The endpoint key arrives with the request, goes into the target for the
run, and is saved nowhere.
"""

import asyncio
import secrets
from collections import deque
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from redflag_backend.quick.interview import LIMIT_REPLY, InterviewBody, interview, user_turns
from redflag_backend.quick.logs import detect_logs
from redflag_backend.quick.pack import (
    AGENT_RULES,
    BOT_TYPES,
    CHATBOT_RULES,
    DEFAULT_RULES,
    production_tests,
    starter_tests,
)
from redflag_backend.quick.recon import recon
from redflag_backend.scan.catalog import load_catalog
from redflag_backend.settings import Settings
from redflag_backend.setups.llm import ModelFailure, SetupLLM
from redflag_backend.setups.models import Endpoint, FieldValue, Rule, SetupData
from redflag_backend.setups.run_api import RunDeps, launch_run
from redflag_backend.setups.store import SetupStore
from redflag_backend.targets.http_target import EndpointConfig

CRITICAL_RULES = {
    CHATBOT_RULES["system_prompt"],
    CHATBOT_RULES["other_users_data"],
    AGENT_RULES["unauthorised_action"],
    AGENT_RULES["external_send"],
}


class CheckBody(BaseModel):
    endpoint: Endpoint
    key: str | None = None


class ProductionTestsBody(BaseModel):
    bot_type: str
    must_never: list[str]


class QuickBody(BaseModel):
    endpoint: Endpoint
    key: str | None = None
    bot_type: str
    purpose: str
    must_never: list[str]
    # Staging runs the full pack. Production runs only the tests the owner picked from the list
    # `production_tests` gives, none of which makes an agent act.
    environment: Literal["staging", "production"] = "staging"
    test_ids: list[str] | None = None
    # An agent can act, so in staging the owner confirms it is a test or sandbox environment.
    sandbox_confirmed: bool = False


def _split_rules(bot_type: str, must_never: list[str]) -> tuple[list[str], list[str]]:
    chosen = [rule.strip() for rule in must_never if rule.strip()]
    defaults = {r.lower() for r in DEFAULT_RULES[bot_type]}
    return chosen, [r for r in chosen if r.lower() not in defaults]


def _error(status: int, kind: str, message: str | None = None) -> JSONResponse:
    body: dict[str, Any] = {"kind": kind}
    if message:
        body["message"] = message
    return JSONResponse(status_code=status, content={"error": body})


def build_quick_router(
    settings: Settings,
    store: SetupStore,
    deps: RunDeps,
    clock: Callable[[], float],
    llm: SetupLLM,
) -> APIRouter:
    router = APIRouter(prefix="/quick-scans")
    recent: deque[float] = deque()
    recent_chats: deque[float] = deque()

    def target(endpoint: Endpoint, key: str | None):  # type: ignore[no-untyped-def]
        return deps.make_target(EndpointConfig(**endpoint.model_dump(), key=key))

    @router.get("/rules")
    async def rules() -> dict[str, Any]:
        """The rules a person can tick for each kind of bot. The page shows exactly these."""
        return {"rules": DEFAULT_RULES}

    @router.post("/production-tests", response_model=None)
    async def production_list(body: ProductionTestsBody) -> dict[str, Any] | JSONResponse:
        """The OWASP tests a person can pick from for a live bot. Nothing is run or saved."""
        if body.bot_type not in BOT_TYPES:
            return _error(422, "bad_bot_type")
        chosen, custom = _split_rules(body.bot_type, body.must_never)
        if not chosen:
            return _error(422, "rules_required")
        catalog = load_catalog()
        tests = []
        for test in production_tests(body.bot_type, chosen, custom):
            risk = catalog.risk(test["risk"])
            tests.append(
                {
                    "id": test["id"],
                    "title": test["title"],
                    "goal": test["goal"],
                    "risk": test["risk"],
                    "risk_name": risk.name if risk else test["risk"],
                    "severity": test["severity"],
                }
            )
        return {"tests": tests}

    @router.post("/interview", response_model=None)
    async def interview_chat(body: InterviewBody) -> dict[str, Any] | JSONResponse:
        """One turn of the step 2 chat. Nothing is saved, and the endpoint key never comes here."""
        cap = settings.quick_interview_max_messages
        if user_turns(body) >= cap:
            return {"reply": LIMIT_REPLY, "limit_reached": True, "messages_left": 0}
        now = clock()
        while recent_chats and now - recent_chats[0] > settings.quick_interview_window_seconds:
            recent_chats.popleft()
        if len(recent_chats) >= settings.quick_interviews_per_window:
            return _error(429, "too_many_chats")
        recent_chats.append(now)
        try:
            answer = await interview(llm, body)
        except ModelFailure as failure:
            return _error(failure.status, failure.kind)
        return {
            **answer.model_dump(),
            "limit_reached": False,
            "messages_left": cap - user_turns(body) - 1,
        }

    @router.post("/check", response_model=None)
    async def check(body: CheckBody) -> dict[str, Any] | JSONResponse:
        now = clock()
        while recent and now - recent[0] > settings.quick_check_window_seconds:
            recent.popleft()
        if len(recent) >= settings.quick_checks_per_window:
            return _error(429, "too_many_checks")
        recent.append(now)
        bot = target(body.endpoint, body.key)
        seen = await bot.test_connection()
        # Logs and the bot's own description are optional, so a reply or description that could
        # not be read is "unknown" (null), not a failure.
        logs = None
        found = None
        if seen.status == "ok":
            logs, found = await asyncio.gather(
                detect_logs(llm, seen.raw_reply), recon(llm, bot, body.endpoint)
            )
        return {
            "status": seen.status,
            "http_status": seen.http_status,
            "raw_reply": seen.raw_reply,
            "parsed_reply": seen.parsed_reply,
            "error": seen.error,
            "logs": logs.model_dump() if logs else None,
            "recon": found.model_dump() if found else None,
        }

    @router.post("", status_code=202, response_model=None)
    async def start(body: QuickBody) -> dict[str, Any] | JSONResponse:
        if body.bot_type not in BOT_TYPES:
            return _error(422, "bad_bot_type")
        if not body.purpose.strip():
            return _error(422, "purpose_required")
        chosen, custom = _split_rules(body.bot_type, body.must_never)
        if not chosen:
            return _error(422, "rules_required")
        live = body.environment == "production"
        if body.bot_type == "agent" and not live and not body.sandbox_confirmed:
            return _error(422, "sandbox_required")
        if deps.gate.busy():
            return _error(409, "scan_running")

        # One hello before anything is created, so a wrong address or key leaves nothing behind.
        seen = await target(body.endpoint, body.key).test_connection()
        if seen.status != "ok":
            return _error(422, "connection_failed", seen.error or "The bot did not answer.")

        if live:
            offered = {t["id"]: t for t in production_tests(body.bot_type, chosen, custom)}
            if not body.test_ids:
                return _error(422, "no_tests_selected")
            if any(i not in offered for i in body.test_ids):
                return _error(422, "unknown_test")
            tests = [offered[i] for i in dict.fromkeys(body.test_ids)]
        else:
            tests = starter_tests(body.bot_type, chosen, custom)

        def fill(data: SetupData) -> None:
            data.fields.purpose = FieldValue(
                value=body.purpose.strip(), source="edited", locked=True
            )
            data.fields.rules = [
                Rule(
                    id=f"r-{secrets.token_hex(3)}",
                    text=rule,
                    kind="forbidden",
                    severity="critical" if rule in CRITICAL_RULES else "high",
                    status="stated",
                    source="user",
                )
                for rule in chosen
            ]
            data.endpoint = body.endpoint
            data.connection.ok = True
            data.connection.attempts = 1

        setup_id = await asyncio.to_thread(store.create_draft)
        await asyncio.to_thread(store.update_draft, setup_id, fill)
        number = await asyncio.to_thread(store.confirm, setup_id)
        await asyncio.to_thread(store.save_tests, setup_id, number, tests)
        view_key = secrets.token_urlsafe(18)
        started = await launch_run(
            store,
            deps,
            setup_id,
            number,
            [t["id"] for t in tests],
            body.key,
            view_key=view_key,
        )
        if isinstance(started, JSONResponse):
            return started
        return {
            "setup_id": setup_id,
            "version": number,
            "scan_id": started["scan_id"],
            "test_count": len(tests),
            "view_key": view_key,
        }

    return router
