"""Attack variations: add rewritten copies of the attack tests of a setup version."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from redflag_backend.attacks.strategies import STRATEGIES, make_variation
from redflag_backend.settings import Settings
from redflag_backend.setups.store import NoSuchSetup, NoSuchVersion, SetupStore


class VariationBody(BaseModel):
    strategies: list[str]
    # The attack tests to vary. Left out, every attack test that is not itself a variation.
    base_ids: list[str] | None = None


def _error(status: int, kind: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"kind": kind}})


def add_variation_routes(router: APIRouter, settings: Settings, store: SetupStore) -> None:
    @router.get("/strategies")
    async def list_strategies() -> dict[str, Any]:
        return {
            "strategies": [
                {"id": s.id, "name": s.name, "description": s.description}
                for s in STRATEGIES.values()
            ]
        }

    @router.post(
        "/setups/{setup_id}/versions/{number}/tests/variations",
        status_code=201,
        response_model=None,
    )
    async def add_variations(
        setup_id: int, number: int, body: VariationBody
    ) -> dict[str, Any] | JSONResponse:
        try:
            tests = await asyncio.to_thread(store.get_tests, setup_id, number)
        except (NoSuchSetup, NoSuchVersion) as missing:
            raise HTTPException(status_code=404, detail="no such version") from missing
        if not tests:
            return _error(409, "no_tests")
        if not body.strategies or any(s not in STRATEGIES for s in body.strategies):
            return _error(422, "unknown_strategy")

        bases = [t for t in tests if t["kind"] == "negative" and "strategy" not in t]
        if body.base_ids is not None:
            by_id = {t["id"]: t for t in bases}
            if not body.base_ids or any(i not in by_id for i in body.base_ids):
                return _error(422, "bad_selection")
            chosen = set(body.base_ids)
            bases = [t for t in bases if t["id"] in chosen]

        known = {t["id"] for t in tests}
        added: list[dict[str, Any]] = []
        for base in bases:
            for strategy_id in dict.fromkeys(body.strategies):
                variation = make_variation(base, strategy_id)
                if variation["id"] not in known:
                    variation.pop("selected", None)
                    added.append(variation)
                    known.add(str(variation["id"]))
        if len(tests) + len(added) > settings.setup_max_tests:
            return _error(422, "test_cap_reached")
        if added:
            await asyncio.to_thread(store.add_tests, setup_id, number, added)
        return {
            "added": [{**t, "selected": True} for t in added],
            "tests": await asyncio.to_thread(store.get_tests, setup_id, number),
        }
