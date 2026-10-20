"""The scan API: list bots, start a scan, read scans, read the catalog. Owner-only."""

import asyncio
import hmac
from collections.abc import Sequence
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from redflag_backend.llm.provider import Provider
from redflag_backend.sandbox.loader import BotRegistry
from redflag_backend.scan.accuracy import accuracy
from redflag_backend.scan.atlas import ATLAS
from redflag_backend.scan.catalog import Catalog
from redflag_backend.scan.gate import ScanGate
from redflag_backend.scan.runner import ScanRunner, new_canary
from redflag_backend.scan.store import ScanStore
from redflag_backend.scan.summary import summarize, zero_counts
from redflag_backend.settings import Settings


class StartScan(BaseModel):
    bot_id: str


class LabelBody(BaseModel):
    correct: Literal["pass", "fail"]


def _error(status: int, kind: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"kind": kind}})


def build_scan_router(
    settings: Settings,
    store: ScanStore,
    registry: BotRegistry,
    runner: ScanRunner,
    providers: Sequence[Provider],
    catalog: Catalog,
    gate: ScanGate,
) -> APIRouter:
    def require_owner(x_owner_token: str | None = Header(default=None)) -> None:
        expected = settings.owner_token
        if not expected or not x_owner_token or not hmac.compare_digest(x_owner_token, expected):
            raise HTTPException(status_code=401, detail="owner token required")

    router = APIRouter(dependencies=[Depends(require_owner)])

    async def interrupt_stale() -> None:
        await asyncio.to_thread(store.interrupt_stale, runner.clock(), settings.scan_stale_seconds)

    @router.get("/bots")
    async def list_bots() -> dict[str, Any]:
        return {
            "bots": [
                {
                    "id": d.config.id,
                    "name": d.config.name,
                    "description": d.config.description,
                    "defenses": sorted(d.defenses),
                    "config_version": d.config.config_version,
                }
                for d in registry.bots.values()
            ],
            "errors": registry.errors,
        }

    @router.get("/catalog")
    async def get_catalog() -> dict[str, Any]:
        return {
            "version": catalog.version,
            "name": catalog.name,
            "source": catalog.source,
            "retrieved": catalog.retrieved,
            "risks": [
                {
                    "id": r.id,
                    "name": r.name,
                    "description": r.description,
                    "atlas": ATLAS.tags(r.id),
                }
                for r in catalog.risks
            ],
            "atlas": ATLAS.meta(),
        }

    @router.post("/scans", status_code=202, response_model=None)
    async def start_scan(body: StartScan) -> dict[str, int] | JSONResponse:
        definition = registry.bots.get(body.bot_id)
        if definition is None:
            return _error(404, "unknown_bot")
        if not any(p.configured for p in providers):
            return _error(503, "no_provider_configured")
        if gate.busy():
            return _error(409, "scan_running")
        canary = new_canary()
        project_id = await asyncio.to_thread(
            store.ensure_project,
            definition.config.id,
            definition.config.name,
            definition.config.description,
        )
        scan_id = await asyncio.to_thread(
            store.create_scan,
            project_id,
            runner.scan_settings(definition, canary, [p.name for p in providers]),
            runner.clock(),
        )
        gate.start(runner.run(scan_id, definition, canary))
        return {"scan_id": scan_id}

    @router.get("/scans")
    async def list_scans(
        bot_id: str | None = None, limit: int = Query(default=50, ge=1, le=200)
    ) -> dict[str, Any]:
        await interrupt_stale()
        scans = await asyncio.to_thread(store.list_scans, bot_id, limit)
        return {"scans": [{**s, "counts": zero_counts(s["counts"])} for s in scans]}

    @router.get("/scans/{scan_id}")
    async def get_scan(scan_id: int) -> dict[str, Any]:
        await interrupt_stale()
        found = await asyncio.to_thread(store.get_scan, scan_id)
        if found is None:
            raise HTTPException(status_code=404, detail="no such scan")
        scan, results = found["scan"], found["results"]
        scan["models_used"] = sorted({r["model"] for r in results if r["model"]})
        scan["previous_scan_id"] = await asyncio.to_thread(store.previous_scan_id, scan_id)
        labels = await asyncio.to_thread(store.labels, scan_id)
        for r in results:
            r["label"] = labels.get(r["test_id"])
        return {"scan": scan, "results": results, "summary": summarize(results, catalog)}

    @router.put("/scans/{scan_id}/results/{test_id}/label", response_model=None)
    async def set_label(
        scan_id: int, test_id: str, body: LabelBody
    ) -> dict[str, str] | JSONResponse:
        if not await asyncio.to_thread(store.has_result, scan_id, test_id):
            return _error(404, "no_such_result")
        await asyncio.to_thread(store.set_label, scan_id, test_id, body.correct, runner.clock())
        return {"correct": body.correct}

    @router.delete("/scans/{scan_id}/results/{test_id}/label")
    async def clear_label(scan_id: int, test_id: str) -> dict[str, bool]:
        await asyncio.to_thread(store.clear_label, scan_id, test_id)
        return {"ok": True}

    @router.get("/judge-accuracy")
    async def judge_accuracy() -> dict[str, Any]:
        rows = await asyncio.to_thread(store.labeled_results)
        return accuracy(rows, settings.judge_accuracy_min_sample)

    return router
