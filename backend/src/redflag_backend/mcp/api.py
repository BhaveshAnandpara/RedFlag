"""The MCP API: look at a server's tools, then run the checks. Owner-only.

The key arrives in the request, goes into the target for this one run and is never saved, logged
or returned. A tool that changes things is only exercised when the owner says the server is a
sandbox and ticks that tool.
"""

import asyncio
import hmac
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from redflag_backend.llm.budget import BudgetCaps
from redflag_backend.mcp.runner import McpScanRunner
from redflag_backend.scan.catalog import Catalog
from redflag_backend.scan.gate import ScanGate
from redflag_backend.scan.store import ScanStore
from redflag_backend.settings import Settings
from redflag_backend.targets.mcp_target import McpConfig, McpTarget

MAX_DESCRIPTION = 500


@dataclass
class McpDeps:
    store: ScanStore
    runner: McpScanRunner
    gate: ScanGate
    clock: Callable[[], float]
    catalog: Catalog
    make_target: Callable[[McpConfig], McpTarget]
    judge_caps: BudgetCaps
    judge_providers: list[str]
    max_calls: int


class Server(BaseModel):
    url: str
    key: str | None = None
    header_name: str = "Authorization"
    header_prefix: str = "Bearer "


class ToolChoice(BaseModel):
    name: str
    effect: Literal["reads", "acts"]


class StartBody(Server):
    exercise: list[ToolChoice] = Field(default_factory=list)
    sandbox_confirmed: bool = False


def _error(status: int, kind: str, message: str | None = None) -> JSONResponse:
    body: dict[str, Any] = {"kind": kind}
    if message:
        body["message"] = message
    return JSONResponse(status_code=status, content={"error": body})


def _config(server: Server) -> McpConfig:
    return McpConfig(
        url=server.url.strip(),
        header_name=server.header_name or "Authorization",
        header_prefix=server.header_prefix,
        key=server.key or None,
    )


def build_mcp_router(settings: Settings, deps: McpDeps) -> APIRouter:
    def require_owner(x_owner_token: str | None = Header(default=None)) -> None:
        expected = settings.owner_token
        if not expected or not x_owner_token or not hmac.compare_digest(x_owner_token, expected):
            raise HTTPException(status_code=401, detail="owner token required")

    router = APIRouter(dependencies=[Depends(require_owner)])

    @router.post("/mcp-scans/check", response_model=None)
    async def check(body: Server) -> dict[str, Any] | JSONResponse:
        listed = await deps.make_target(_config(body)).list_tools()
        if listed.status == "error":
            return _error(422, "connection_failed", listed.error)
        return {
            "server": {"name": listed.server_name, "version": listed.server_version},
            "tools": [
                {
                    "name": t.name,
                    "description": t.description[:MAX_DESCRIPTION],
                    "params": sorted((t.input_schema.get("properties") or {}).keys()),
                    # Only "reads" if the server itself says so. Anything else is for the owner.
                    "effect_hint": "reads" if t.read_only_hint else "unknown",
                }
                for t in listed.tools
            ],
        }

    @router.post("/mcp-scans", status_code=202, response_model=None)
    async def start(body: StartBody) -> dict[str, int] | JSONResponse:
        if any(choice.effect == "acts" for choice in body.exercise) and not body.sandbox_confirmed:
            return _error(422, "sandbox_required")
        if deps.gate.busy():
            return _error(409, "scan_running")
        target = deps.make_target(_config(body))
        listed = await target.list_tools()
        if listed.status == "error":
            return _error(422, "connection_failed", listed.error)
        names = {t.name for t in listed.tools}
        exercise = {choice.name: choice.effect for choice in body.exercise}
        if not set(exercise) <= names or len(exercise) != len(body.exercise):
            return _error(422, "unknown_tool")

        host = (urlsplit(body.url).hostname or "").lower()
        slug = f"mcp-{host}"
        project_id = await asyncio.to_thread(
            deps.store.ensure_project, slug, f"MCP server ({host})", "An MCP server under test."
        )
        settings_doc: dict[str, Any] = {
            "bot_id": slug,
            "bot_name": f"MCP server ({host})",
            "bot_config_version": 1,
            "bot_defenses": [],
            "catalog_version": deps.catalog.version,
            "suite_version": 0,
            "test_count": 0,
            "canary": "",
            "providers": [],
            "judge_providers": deps.judge_providers,
            "judge_budget": {
                "requests": deps.judge_caps.requests,
                "tokens": deps.judge_caps.tokens,
                "seconds": deps.judge_caps.seconds,
            },
            "budget": {"requests": deps.max_calls, "tokens": 0, "seconds": 0, "concurrency": 1},
            "mcp": {
                "target_host": host,
                "server": {"name": listed.server_name, "version": listed.server_version},
                "tool_count": len(listed.tools),
                "exercised": [
                    {"name": name, "effect": effect} for name, effect in exercise.items()
                ],
                "sandbox_confirmed": body.sandbox_confirmed,
            },
        }
        scan_id = await asyncio.to_thread(
            deps.store.create_scan, project_id, settings_doc, deps.clock()
        )
        deps.gate.start(deps.runner.run(scan_id, target, listed.tools, exercise, host))
        return {"scan_id": scan_id}

    return router
