"""The quick scan: a hello check, and one call that sets a bot up and runs the starter pack.

Owner-only for now. There is no select step: the pack is fixed, so nothing needs choosing. The
endpoint key arrives with the request, goes into the target for the run, and is saved nowhere.
"""

import asyncio
import hmac
import secrets
from collections import deque
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from redflag_backend.quick.pack import (
    AGENT_RULES,
    BOT_TYPES,
    CHATBOT_RULES,
    DEFAULT_RULES,
    starter_tests,
)
from redflag_backend.settings import Settings
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


class QuickBody(BaseModel):
    endpoint: Endpoint
    key: str | None = None
    bot_type: str
    purpose: str
    must_never: list[str]
    # An agent can act, so the owner confirms it is pointed at a test or sandbox environment.
    sandbox_confirmed: bool = False


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
) -> APIRouter:
    def require_owner(x_owner_token: str | None = Header(default=None)) -> None:
        expected = settings.owner_token
        if not expected or not x_owner_token or not hmac.compare_digest(x_owner_token, expected):
            raise HTTPException(status_code=401, detail="owner token required")

    router = APIRouter(prefix="/quick-scans", dependencies=[Depends(require_owner)])
    recent: deque[float] = deque()

    def target(endpoint: Endpoint, key: str | None):  # type: ignore[no-untyped-def]
        return deps.make_target(EndpointConfig(**endpoint.model_dump(), key=key))

    @router.get("/rules")
    async def rules() -> dict[str, Any]:
        """The rules a person can tick for each kind of bot. The page shows exactly these."""
        return {"rules": DEFAULT_RULES}

    @router.post("/check", response_model=None)
    async def check(body: CheckBody) -> dict[str, Any] | JSONResponse:
        now = clock()
        while recent and now - recent[0] > settings.quick_check_window_seconds:
            recent.popleft()
        if len(recent) >= settings.quick_checks_per_window:
            return _error(429, "too_many_checks")
        recent.append(now)
        seen = await target(body.endpoint, body.key).test_connection()
        return {
            "status": seen.status,
            "http_status": seen.http_status,
            "raw_reply": seen.raw_reply,
            "parsed_reply": seen.parsed_reply,
            "error": seen.error,
        }

    @router.post("", status_code=202, response_model=None)
    async def start(body: QuickBody) -> dict[str, Any] | JSONResponse:
        if body.bot_type not in BOT_TYPES:
            return _error(422, "bad_bot_type")
        if not body.purpose.strip():
            return _error(422, "purpose_required")
        chosen = [rule.strip() for rule in body.must_never if rule.strip()]
        if not chosen:
            return _error(422, "rules_required")
        if body.bot_type == "agent" and not body.sandbox_confirmed:
            return _error(422, "sandbox_required")
        if deps.gate.busy():
            return _error(409, "scan_running")

        # One hello before anything is created, so a wrong address or key leaves nothing behind.
        seen = await target(body.endpoint, body.key).test_connection()
        if seen.status != "ok":
            return _error(422, "connection_failed", seen.error or "The bot did not answer.")

        defaults = {r.lower() for r in DEFAULT_RULES[body.bot_type]}
        custom = [r for r in chosen if r.lower() not in defaults]
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
        started = await launch_run(
            store, deps, setup_id, number, [t["id"] for t in tests], body.key
        )
        if isinstance(started, JSONResponse):
            return started
        return {
            "setup_id": setup_id,
            "version": number,
            "scan_id": started["scan_id"],
            "test_count": len(tests),
        }

    return router
