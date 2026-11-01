"""Reading back a scan started from the open quick scan or MCP page.

Only a scan that was started through those pages has a secret view key in its settings, and only
that key reads it. The key is never returned, and neither are the owner's labels. No other scan
can be read this way.
"""

import asyncio
import hmac
import time
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from redflag_backend.scan.catalog import Catalog
from redflag_backend.scan.store import ScanStore
from redflag_backend.scan.summary import summarize
from redflag_backend.settings import Settings
from redflag_backend.specs.results import ResultStore


class AnswerBody(BaseModel):
    action: Literal["retry", "stop"]


def build_open_scan_router(
    settings: Settings,
    store: ScanStore,
    catalog: Catalog,
    proofs: ResultStore,
    answer_run: Callable[[int, str], bool],
) -> APIRouter:
    router = APIRouter()

    @router.post("/open-scans/{scan_id}/answer", response_model=None)
    async def answer(scan_id: int, key: str, body: AnswerBody) -> dict[str, bool] | JSONResponse:
        """Retry or stop a run that paused because the bot stopped answering. Only the person who
        started the scan has the key."""
        found = await asyncio.to_thread(store.get_scan, scan_id)
        expected = found["scan"]["settings"].get("view_key") if found else None
        if not found or not expected or not hmac.compare_digest(str(expected), key):
            raise HTTPException(status_code=404, detail="no such scan")
        if not answer_run(scan_id, body.action):
            return JSONResponse(status_code=409, content={"error": {"kind": "not_waiting"}})
        return {"ok": True}

    @router.get("/open-scans/{scan_id}")
    async def read(scan_id: int, key: str) -> dict[str, Any]:
        found = await asyncio.to_thread(store.get_scan, scan_id)
        expected = found["scan"]["settings"].get("view_key") if found else None
        if not found or not expected or not hmac.compare_digest(str(expected), key):
            raise HTTPException(status_code=404, detail="no such scan")
        # The same "no progress for a while" rule as the owner's read.
        await asyncio.to_thread(store.interrupt_stale, time.time(), settings.scan_stale_seconds)
        found = await asyncio.to_thread(store.get_scan, scan_id)
        assert found is not None
        scan, results = found["scan"], found["results"]
        scan["settings"] = {k: v for k, v in scan["settings"].items() if k != "view_key"}
        scan["models_used"] = sorted({r["model"] for r in results if r["model"]})
        scan["previous_scan_id"] = None
        saved = await asyncio.to_thread(proofs.proofs_for_scan, scan_id)
        for r in results:
            r["proof"] = saved.get(r["test_id"])
        return {"scan": scan, "results": results, "summary": summarize(results, catalog)}

    return router
