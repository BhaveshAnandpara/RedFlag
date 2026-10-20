"""API tokens (owner side) and the CI endpoints (token side).

The owner makes a token for one setup and sees it once. A build then sends it as a bearer token to
start a run of that setup and to read the result with a gate. The token cannot reach anything else:
not other setups, not demo scans, not the owner's endpoints. The owner password is not accepted
here either.
"""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from redflag_backend.ci.gate import THRESHOLDS, evaluate
from redflag_backend.ci.tokens import CiTokenStore
from redflag_backend.setups.run_api import RunDeps, launch_run
from redflag_backend.setups.store import NoSuchSetup, SetupStore


class TokenBody(BaseModel):
    label: str = Field(default="ci", min_length=1, max_length=60)


class CiRunBody(BaseModel):
    key: str | None = None
    version: int | None = None
    test_ids: list[str] | None = None
    fail_on: str = "critical"
    fail_on_unclear: bool = False


def _error(status: int, kind: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"kind": kind}})


def add_token_routes(router: APIRouter, store: SetupStore, tokens: CiTokenStore) -> None:
    """Owner-only: make, list and revoke the tokens of a setup."""

    async def require_setup(setup_id: int) -> None:
        try:
            await asyncio.to_thread(store.get_draft, setup_id)
        except NoSuchSetup as missing:
            raise HTTPException(status_code=404, detail="no such setup") from missing

    @router.post("/setups/{setup_id}/ci-tokens", status_code=201)
    async def create_token(setup_id: int, body: TokenBody) -> dict[str, Any]:
        await require_setup(setup_id)
        token_id, token = await asyncio.to_thread(tokens.create, setup_id, body.label)
        # The only time the token is shown: it is stored as a hash.
        return {"id": token_id, "label": body.label, "token": token}

    @router.get("/setups/{setup_id}/ci-tokens")
    async def list_tokens(setup_id: int) -> dict[str, Any]:
        await require_setup(setup_id)
        return {"tokens": await asyncio.to_thread(tokens.list, setup_id)}

    @router.delete("/setups/{setup_id}/ci-tokens/{token_id}", status_code=204, response_model=None)
    async def revoke_token(setup_id: int, token_id: int) -> Response:
        await require_setup(setup_id)
        if not await asyncio.to_thread(tokens.revoke, setup_id, token_id):
            return _error(404, "no_such_token")
        return Response(status_code=204)


def build_ci_router(tokens: CiTokenStore, store: SetupStore, deps: RunDeps) -> APIRouter:
    async def current_setup(authorization: str | None = Header(default=None)) -> int:
        scheme, _, value = (authorization or "").partition(" ")
        setup_id = (
            await asyncio.to_thread(tokens.authenticate, value.strip())
            if scheme.lower() == "bearer" and value.strip()
            else None
        )
        if setup_id is None:
            raise HTTPException(status_code=401, detail="a valid API token is required")
        return setup_id

    router = APIRouter(prefix="/ci")

    @router.post("/runs", status_code=202, response_model=None)
    async def start(
        body: CiRunBody, setup_id: int = Depends(current_setup)
    ) -> dict[str, Any] | JSONResponse:
        if body.fail_on not in THRESHOLDS:
            return _error(422, "bad_threshold")
        versions = await asyncio.to_thread(store.list_versions, setup_id)
        if body.version is None:
            if not versions:
                return _error(404, "no_version")
            number = max(v["number"] for v in versions)
        elif any(v["number"] == body.version for v in versions):
            number = body.version
        else:
            raise HTTPException(status_code=404, detail="no such version")
        ids = body.test_ids
        if ids is None:
            tests = await asyncio.to_thread(store.get_tests, setup_id, number)
            if not tests:
                return _error(409, "no_tests")
            ids = [t["id"] for t in tests if t["selected"]]
        started = await launch_run(
            store,
            deps,
            setup_id,
            number,
            ids,
            body.key,
            gate={"fail_on": body.fail_on, "fail_on_unclear": body.fail_on_unclear},
        )
        if isinstance(started, JSONResponse):
            return started
        return {"run_id": started["scan_id"], "status_url": f"/ci/runs/{started['scan_id']}"}

    @router.get("/runs/{run_id}")
    async def read(
        run_id: int,
        fail_on: str | None = None,
        fail_on_unclear: bool | None = None,
        setup_id: int = Depends(current_setup),
    ) -> dict[str, Any]:
        if fail_on is not None and fail_on not in THRESHOLDS:
            raise HTTPException(status_code=422, detail="bad threshold")
        found = await asyncio.to_thread(deps.scan_store.get_scan, run_id)
        setup = found["scan"]["settings"].get("setup") if found else None
        # A token only ever sees runs of its own setup. Anything else looks like it is not there.
        if found is None or not setup or int(setup["setup_id"]) != setup_id:
            raise HTTPException(status_code=404, detail="no such run")
        # What the caller asked for when the run started, unless this request says otherwise.
        remembered = setup.get("gate") or {}
        threshold = fail_on or remembered.get("fail_on") or "critical"
        strict = (
            fail_on_unclear
            if fail_on_unclear is not None
            else bool(remembered.get("fail_on_unclear", False))
        )
        results = found["results"]
        counts = {s: sum(1 for r in results if r["status"] == s) for s in
                  ("pass", "fail", "inconclusive", "error", "not_applicable")}  # fmt: skip
        return {
            "run_id": run_id,
            "status": found["scan"]["status"],
            "setup": {"setup_id": setup_id, "version": setup["version"]},
            "counts": counts,
            "tests": [
                {
                    "test_id": r["test_id"],
                    "title": r["title"],
                    "status": r["status"],
                    "severity": r.get("severity"),
                }
                for r in results
            ],
            "failures": [
                {
                    "test_id": r["test_id"],
                    "title": r["title"],
                    "severity": r.get("severity"),
                    "evidence": r["evidence"],
                }
                for r in results
                if r["status"] == "fail"
            ],
            "gate": evaluate(found, threshold, strict),
        }

    return router
