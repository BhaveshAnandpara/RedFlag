"""Running the ticked tests of a confirmed setup version against the user's real endpoint.

The ticked ids in the request are the owner's confirmation: no ids, an empty list or an unknown id
is refused and nothing is sent anywhere. The endpoint key arrives in the request, goes into the
target for this one run, and is never saved, logged or returned.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from redflag_backend.judge.judge import ToolDescription
from redflag_backend.llm.budget import BudgetCaps
from redflag_backend.scan.catalog import Catalog
from redflag_backend.scan.gate import ScanGate
from redflag_backend.scan.store import ScanStore
from redflag_backend.scan.target_runner import TargetScanRunner
from redflag_backend.setups.models import Endpoint
from redflag_backend.setups.store import NoSuchSetup, NoSuchVersion, SetupStore
from redflag_backend.setups.supervisor import judge_context_for_version, render_judge_context
from redflag_backend.targets.http_target import EndpointConfig, HttpTarget

TargetFactory = Callable[[EndpointConfig], HttpTarget]


@dataclass
class RunDeps:
    scan_store: ScanStore
    runner: TargetScanRunner
    gate: ScanGate
    clock: Callable[[], float]
    catalog: Catalog
    make_target: TargetFactory
    judge_caps: BudgetCaps
    judge_providers: list[str]
    judge_prompt_version: int


class RunBody(BaseModel):
    test_ids: list[str] | None = None
    key: str | None = None


def _error(status: int, kind: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"kind": kind}})


async def launch_run(
    store: SetupStore,
    deps: RunDeps,
    setup_id: int,
    number: int,
    ids: list[str] | None,
    key: str | None,
    rerun_of: int | None = None,
    gate: dict[str, Any] | None = None,
) -> dict[str, int] | JSONResponse:
    """Start a run of the chosen tests of a confirmed setup version. Used by the owner's page,
    by Run again and by the CI endpoints, so they all keep the same rules."""
    try:
        version = await asyncio.to_thread(store.get_version, setup_id, number)
        ref = await asyncio.to_thread(store.version_ref, setup_id, number)
    except (NoSuchSetup, NoSuchVersion) as missing:
        raise HTTPException(status_code=404, detail="no such version") from missing
    tests = await asyncio.to_thread(store.get_tests, setup_id, number)
    if not tests:
        return _error(409, "no_tests")
    known = {t["id"] for t in tests}
    if not ids or len(set(ids)) != len(ids) or not set(ids) <= known:
        return _error(422, "bad_selection")
    if deps.gate.busy():
        return _error(409, "scan_running")

    chosen = [t for t in tests if t["id"] in set(ids)]
    await asyncio.to_thread(store.set_selection, setup_id, number, ids)
    endpoint = Endpoint.model_validate(version["endpoint"])
    host = (urlsplit(endpoint.url).hostname or "").lower()
    context = judge_context_for_version(version)
    tools = [ToolDescription(t.name, t.effect, t.description) for t in context.tools]
    rules = [
        {"text": r["text"], "kind": r["kind"], "status": r["status"]}
        for r in version["fields"]["rules"]
    ]
    settings: dict[str, Any] = {
        "bot_id": ref["slug"],
        "bot_name": f"Your bot (setup {setup_id}, version {number})",
        "bot_config_version": number,
        "bot_defenses": [],
        "catalog_version": deps.catalog.version,
        "suite_version": 0,  # generated tests, not the fixed library
        "test_count": len(chosen),
        "canary": "",
        "providers": [],
        "judge_prompt_version": deps.judge_prompt_version,
        "judge_providers": deps.judge_providers,
        "judge_budget": {
            "requests": deps.judge_caps.requests,
            "tokens": deps.judge_caps.tokens,
            "seconds": deps.judge_caps.seconds,
        },
        "budget": {
            "requests": deps.runner.max_requests,
            "tokens": 0,
            "seconds": 0,
            "concurrency": 1,
        },
        "setup": {
            "setup_id": setup_id,
            "version": number,
            "selected_test_ids": ids,
            "target_host": host,
            "rules": rules,
            **({"rerun_of": rerun_of} if rerun_of is not None else {}),
            # How a CI caller wants the result judged, remembered with the run
            **({"gate": gate} if gate is not None else {}),
        },
    }
    scan_id = await asyncio.to_thread(
        deps.scan_store.create_scan,
        ref["project_id"],
        settings,
        deps.clock(),
        ref["version_id"],
    )
    # The key lives only inside this object, for the length of the run.
    target = deps.make_target(EndpointConfig(**endpoint.model_dump(), key=key))
    deps.gate.start(
        deps.runner.run(scan_id, chosen, target, render_judge_context(context), tools, host)
    )
    return {"scan_id": scan_id}


def add_run_routes(router: APIRouter, store: SetupStore, deps: RunDeps) -> None:
    @router.post("/setups/{setup_id}/versions/{number}/runs", status_code=202, response_model=None)
    async def start_run(setup_id: int, number: int, body: RunBody) -> dict[str, int] | JSONResponse:
        return await launch_run(store, deps, setup_id, number, body.test_ids, body.key)

    @router.post("/scans/{scan_id}/rerun", status_code=202, response_model=None)
    async def rerun(scan_id: int, body: RunBody) -> dict[str, int] | JSONResponse:
        """Run a finished real-bot scan again: the same setup version and the same tests."""
        found = await asyncio.to_thread(deps.scan_store.get_scan, scan_id)
        if found is None:
            raise HTTPException(status_code=404, detail="no such scan")
        setup = found["scan"]["settings"].get("setup")
        if not setup:
            return _error(422, "not_a_setup_scan")
        return await launch_run(
            store,
            deps,
            int(setup["setup_id"]),
            int(setup["version"]),
            list(setup["selected_test_ids"]),
            body.key,
            scan_id,
        )
