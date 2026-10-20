"""The setup API: drafts, rules, the endpoint, the connection test and confirmed versions.

Owner-only. The endpoint key is accepted only in the body of a connection test (and, later, a
run), used for that one call and never saved, logged or returned.
"""

import asyncio
import hmac
import secrets
from collections.abc import Iterable
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from redflag_backend.settings import Settings
from redflag_backend.setups.chat_api import add_chat_routes
from redflag_backend.setups.llm import SetupLLM
from redflag_backend.setups.models import (
    MAX_CONNECTION_TESTS,
    Endpoint,
    Rule,
    RuleKind,
    SetupData,
    Severity,
    required_status,
)
from redflag_backend.setups.run_api import RunDeps, add_run_routes
from redflag_backend.setups.store import NoSuchSetup, NoSuchVersion, SetupStore
from redflag_backend.setups.tests_api import add_test_routes
from redflag_backend.setups.variations_api import add_variation_routes
from redflag_backend.targets.http_target import (
    EndpointConfig,
    HttpTarget,
    Resolver,
    system_resolver,
)


class PurposeBody(BaseModel):
    value: str


class RuleBody(BaseModel):
    text: str
    kind: RuleKind
    severity: Severity = "high"
    # A user can add a rule they are unsure of, but not one "inferred" by a model
    status: Literal["stated", "unclear"] = "stated"


class RuleEdit(BaseModel):
    text: str | None = None
    kind: RuleKind | None = None
    severity: Severity | None = None


class ConnectionBody(BaseModel):
    key: str | None = None


def _error(status: int, kind: str, **more: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"kind": kind, **more}})


def build_setup_router(
    settings: Settings,
    store: SetupStore,
    llm: SetupLLM,
    runs: RunDeps,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    resolver: Resolver | None = None,
    blocked_hosts: Iterable[str] = (),
) -> APIRouter:
    def require_owner(x_owner_token: str | None = Header(default=None)) -> None:
        expected = settings.owner_token
        if not expected or not x_owner_token or not hmac.compare_digest(x_owner_token, expected):
            raise HTTPException(status_code=401, detail="owner token required")

    router = APIRouter(dependencies=[Depends(require_owner)])
    blocked = list(blocked_hosts)

    async def read(setup_id: int) -> dict[str, Any]:
        try:
            data, slug, _ = await asyncio.to_thread(store.get_draft, setup_id)
        except NoSuchSetup as missing:
            raise HTTPException(status_code=404, detail="no such setup") from missing
        return {
            "setup_id": setup_id,
            "project_slug": slug,
            "fields": data.fields.model_dump(),
            "endpoint": data.endpoint.model_dump(),
            "connection": data.connection.model_dump(),
            "required": required_status(data),
            "chat": [turn.model_dump() for turn in data.chat],
            "files": [{"name": f.name, "bytes": len(f.content.encode())} for f in data.files],
            "contexts": data.contexts.model_dump() if data.contexts else None,
            "followups_asked": data.followups_asked,
            "user_messages": data.user_messages,
        }

    async def change(setup_id: int, apply: Any) -> Any:
        try:
            return await asyncio.to_thread(store.update_draft, setup_id, apply)
        except NoSuchSetup as missing:
            raise HTTPException(status_code=404, detail="no such setup") from missing

    @router.get("/setups")
    async def list_setups() -> dict[str, Any]:
        return {"setups": await asyncio.to_thread(store.list_drafts)}

    @router.post("/setups", status_code=201)
    async def create_setup() -> dict[str, int]:
        return {"setup_id": await asyncio.to_thread(store.create_draft)}

    @router.get("/setups/{setup_id}")
    async def get_setup(setup_id: int) -> dict[str, Any]:
        return await read(setup_id)

    @router.put("/setups/{setup_id}/purpose")
    async def set_purpose(setup_id: int, body: PurposeBody) -> dict[str, Any]:
        def apply(data: SetupData) -> None:
            data.fields.purpose.value = body.value
            data.fields.purpose.source = "edited"
            data.fields.purpose.locked = True

        await change(setup_id, apply)
        return await read(setup_id)

    @router.post("/setups/{setup_id}/purpose/unlock")
    async def unlock_purpose(setup_id: int) -> dict[str, Any]:
        def apply(data: SetupData) -> None:
            data.fields.purpose.locked = False

        await change(setup_id, apply)
        return await read(setup_id)

    @router.post("/setups/{setup_id}/rules", status_code=201)
    async def add_rule(setup_id: int, body: RuleBody) -> dict[str, Any]:
        rule = Rule(
            id=f"r-{secrets.token_hex(3)}",
            text=body.text,
            kind=body.kind,
            severity=body.severity,
            status=body.status,
            source="user",
        )

        def apply(data: SetupData) -> None:
            data.fields.rules.append(rule)

        await change(setup_id, apply)
        return rule.model_dump()

    def find_rule(data: SetupData, rule_id: str) -> Rule | None:
        return next((r for r in data.fields.rules if r.id == rule_id), None)

    @router.put("/setups/{setup_id}/rules/{rule_id}", response_model=None)
    async def edit_rule(
        setup_id: int, rule_id: str, body: RuleEdit
    ) -> dict[str, Any] | JSONResponse:
        def apply(data: SetupData) -> dict[str, Any] | None:
            rule = find_rule(data, rule_id)
            if rule is None:
                return None
            for name in ("text", "kind", "severity"):
                value = getattr(body, name)
                if value is not None:
                    setattr(rule, name, value)
            rule.source, rule.locked = "edited", True
            return rule.model_dump()

        result = await change(setup_id, apply)
        return result if result is not None else _error(404, "no_such_rule")

    @router.post("/setups/{setup_id}/rules/{rule_id}/confirm", response_model=None)
    async def confirm_rule(setup_id: int, rule_id: str) -> dict[str, Any] | JSONResponse:
        def apply(data: SetupData) -> dict[str, Any] | None:
            rule = find_rule(data, rule_id)
            if rule is None:
                return None
            rule.status, rule.question = "stated", None
            return rule.model_dump()

        result = await change(setup_id, apply)
        return result if result is not None else _error(404, "no_such_rule")

    @router.delete("/setups/{setup_id}/rules/{rule_id}", status_code=204, response_model=None)
    async def delete_rule(setup_id: int, rule_id: str) -> Response:
        def apply(data: SetupData) -> bool:
            kept = [r for r in data.fields.rules if r.id != rule_id]
            found = len(kept) != len(data.fields.rules)
            data.fields.rules = kept
            return found

        if not await change(setup_id, apply):
            return _error(404, "no_such_rule")
        return Response(status_code=204)

    @router.put("/setups/{setup_id}/endpoint")
    async def set_endpoint(setup_id: int, body: Endpoint) -> dict[str, Any]:
        def apply(data: SetupData) -> None:
            data.endpoint = body
            data.connection.ok = False  # a changed endpoint has not been tested yet

        await change(setup_id, apply)
        return await read(setup_id)

    @router.post("/setups/{setup_id}/connection-test", response_model=None)
    async def connection_test(setup_id: int, body: ConnectionBody) -> dict[str, Any] | JSONResponse:
        def reserve(data: SetupData) -> Endpoint | None:
            if data.connection.attempts >= MAX_CONNECTION_TESTS:
                return None
            data.connection.attempts += 1
            return data.endpoint

        endpoint = await change(setup_id, reserve)
        if endpoint is None:
            return _error(429, "too_many_tests")
        target = HttpTarget(
            EndpointConfig(**endpoint.model_dump(), key=body.key),
            resolver=resolver or system_resolver,
            transport=transport,
            blocked_hosts=blocked,
        )
        check = await target.test_connection()

        def record(data: SetupData) -> int:
            data.connection.ok = check.status == "ok"
            data.connection.last_error = check.error or None
            return MAX_CONNECTION_TESTS - data.connection.attempts

        left = await change(setup_id, record)
        return {
            "status": check.status,
            "http_status": check.http_status,
            "raw_reply": check.raw_reply,
            "parsed_reply": check.parsed_reply,
            "error": check.error,
            "attempts_left": left,
        }

    @router.post("/setups/{setup_id}/confirm", status_code=201, response_model=None)
    async def confirm(setup_id: int) -> dict[str, int] | JSONResponse:
        try:
            data, _, _ = await asyncio.to_thread(store.get_draft, setup_id)
        except NoSuchSetup as missing:
            raise HTTPException(status_code=404, detail="no such setup") from missing
        required = required_status(data)
        if not required["ready"]:
            unmet = [name for name, met in required.items() if name != "ready" and not met]
            return _error(409, "not_ready", missing=unmet)
        return {"version": await asyncio.to_thread(store.confirm, setup_id)}

    @router.get("/setups/{setup_id}/versions")
    async def list_versions(setup_id: int) -> dict[str, Any]:
        try:
            return {"versions": await asyncio.to_thread(store.list_versions, setup_id)}
        except NoSuchSetup as missing:
            raise HTTPException(status_code=404, detail="no such setup") from missing

    @router.get("/setups/{setup_id}/versions/{number}")
    async def get_version(setup_id: int, number: int) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(store.get_version, setup_id, number)
        except (NoSuchSetup, NoSuchVersion) as missing:
            raise HTTPException(status_code=404, detail="no such version") from missing

    add_chat_routes(router, settings, store, llm)
    add_test_routes(router, store, llm)
    add_variation_routes(router, settings, store)
    add_run_routes(router, store, runs)
    return router
