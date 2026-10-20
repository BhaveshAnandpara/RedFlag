"""Reading back a scan started from the open quick scan or MCP page.

Only a scan that was started through those pages has a secret view key in its settings, and only
that key reads it. The key is never returned, and neither are the owner's labels. Without
OPEN_QUICK_AND_MCP the route does not exist.
"""

import asyncio
import hmac
import time
from typing import Any

from fastapi import APIRouter, HTTPException

from redflag_backend.scan.catalog import Catalog
from redflag_backend.scan.store import ScanStore
from redflag_backend.scan.summary import summarize
from redflag_backend.settings import Settings


def build_open_scan_router(settings: Settings, store: ScanStore, catalog: Catalog) -> APIRouter:
    router = APIRouter()

    @router.get("/open-scans/{scan_id}")
    async def read(scan_id: int, key: str) -> dict[str, Any]:
        if not settings.open_quick_and_mcp:
            raise HTTPException(status_code=404, detail="no such scan")
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
        return {"scan": scan, "results": results, "summary": summarize(results, catalog)}

    return router
