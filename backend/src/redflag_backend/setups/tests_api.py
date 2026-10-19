"""Generating, listing and (in the next phase) selecting the tests for a confirmed setup version."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from redflag_backend.setups.generator import (
    GENERATOR_SYSTEM,
    GeneratorAnswer,
    build_prompt,
    finalize,
)
from redflag_backend.setups.llm import ModelFailure, SetupLLM
from redflag_backend.setups.store import NoSuchSetup, NoSuchVersion, SetupStore


def add_test_routes(router: APIRouter, store: SetupStore, llm: SetupLLM) -> None:
    async def version_of(setup_id: int, number: int) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(store.get_version, setup_id, number)
        except (NoSuchSetup, NoSuchVersion) as missing:
            raise HTTPException(status_code=404, detail="no such version") from missing

    @router.post("/setups/{setup_id}/versions/{number}/tests", status_code=201, response_model=None)
    async def generate(setup_id: int, number: int) -> dict[str, Any] | JSONResponse:
        version = await version_of(setup_id, number)
        try:
            answer = await llm.ask(
                setup_id, "generator", GENERATOR_SYSTEM, build_prompt(version), GeneratorAnswer
            )
        except ModelFailure as failure:
            return JSONResponse(
                status_code=failure.status, content={"error": {"kind": failure.kind}}
            )
        tests = finalize(answer, version)
        if not tests:
            return JSONResponse(status_code=502, content={"error": {"kind": "bad_model_answer"}})
        await asyncio.to_thread(store.save_tests, setup_id, number, tests)
        return {"tests": await asyncio.to_thread(store.get_tests, setup_id, number)}

    @router.get("/setups/{setup_id}/versions/{number}/tests")
    async def list_tests(setup_id: int, number: int) -> dict[str, Any]:
        await version_of(setup_id, number)
        return {"tests": await asyncio.to_thread(store.get_tests, setup_id, number)}
