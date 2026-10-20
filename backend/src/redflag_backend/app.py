import time
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from redflag_backend.attacks.attacker import Attacker
from redflag_backend.judge.judge import PROMPT_VERSION, Judge
from redflag_backend.llm.api import build_llm_router
from redflag_backend.llm.budget import BudgetBook, BudgetCaps
from redflag_backend.llm.provider import Provider
from redflag_backend.llm.providers.factory import build_providers
from redflag_backend.llm.router import Router
from redflag_backend.sandbox.loader import BOTS_DIR, load_bots
from redflag_backend.scan.api import build_scan_router
from redflag_backend.scan.bot_models import bot_budget_caps, build_bot_providers, build_bot_router
from redflag_backend.scan.catalog import load_catalog
from redflag_backend.scan.gate import ScanGate
from redflag_backend.scan.runner import ScanRunner
from redflag_backend.scan.store import ScanStore
from redflag_backend.scan.suite import load_suite
from redflag_backend.scan.target_runner import TargetScanRunner
from redflag_backend.settings import Settings
from redflag_backend.setups.api import build_setup_router
from redflag_backend.setups.llm import SetupLLM
from redflag_backend.setups.run_api import RunDeps
from redflag_backend.setups.store import SetupStore
from redflag_backend.targets.http_target import (
    EndpointConfig,
    HttpTarget,
    Resolver,
    system_resolver,
)


def create_app(
    settings: Settings,
    providers: Sequence[Provider] | None = None,
    clock: Callable[[], float] | None = None,
    bot_providers: Sequence[Provider] | None = None,
    bots_dir: Path | None = None,
    target_transport: httpx.AsyncBaseTransport | None = None,
    target_resolver: Resolver | None = None,
) -> FastAPI:
    now = clock or time.time
    engine = create_engine(
        settings.database_url,
        connect_args={"connect_timeout": int(settings.db_timeout_seconds)},
    )
    scan_store = ScanStore(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # A scan that was running when the backend stopped can no longer be running.
        try:
            scan_store.interrupt_stale(now(), settings.scan_stale_seconds)
        except SQLAlchemyError:
            pass  # the database may still be waking up; reading a scan applies the same rule
        yield
        engine.dispose()  # hand the database connections back when the app stops

    app = FastAPI(title="Redflag", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["X-Owner-Token", "Content-Type"],
    )
    active_providers = build_providers(settings) if providers is None else providers
    app.include_router(build_llm_router(settings, active_providers, engine, clock))

    # The demo bots have their own keys, router and budget, apart from Redflag's own router.
    active_bot_providers = (
        build_bot_providers(settings) if bot_providers is None else list(bot_providers)
    )
    catalog = load_catalog()
    # The AI judge uses Redflag's own models (not the bots' keys), through its own router.
    judge = Judge(
        Router(active_providers, clock=now),
        clock=now,
        rate_wait=settings.scan_rate_limit_wait_seconds,
        rate_wait_max=settings.scan_rate_limit_max_wait_seconds,
        rate_retries=settings.scan_rate_limit_retries,
    )
    runner = ScanRunner(
        store=scan_store,
        router=build_bot_router(active_bot_providers, now),
        caps=bot_budget_caps(settings),
        clock=now,
        suite=load_suite(),
        catalog=catalog,
        judge=judge,
        judge_caps=BudgetCaps(
            requests=settings.judge_budget_max_requests,
            tokens=settings.judge_budget_max_tokens,
            seconds=settings.judge_budget_max_seconds,
            concurrency=1,
        ),
        judge_providers=[p.name for p in active_providers if p.configured],
        rate_wait=settings.scan_rate_limit_wait_seconds,
        rate_wait_max=settings.scan_rate_limit_max_wait_seconds,
        rate_retries=settings.scan_rate_limit_retries,
    )
    gate = ScanGate()  # one scan at a time, whether it is a demo bot or a real one
    app.include_router(
        build_scan_router(
            settings,
            scan_store,
            load_bots(bots_dir or BOTS_DIR),
            runner,
            active_bot_providers,
            catalog,
            gate,
        )
    )

    # Setups: what the owner tells Redflag about their own bot. Never calls an address inside.
    setup_llm = SetupLLM(
        Router(active_providers, clock=now),
        BudgetBook(
            BudgetCaps(
                requests=settings.setup_budget_max_requests,
                tokens=settings.setup_budget_max_tokens,
                seconds=settings.setup_budget_max_seconds,
                concurrency=1,
            ),
            now,
        ),
    )
    judge_caps = BudgetCaps(
        requests=settings.judge_budget_max_requests,
        tokens=settings.judge_budget_max_tokens,
        seconds=settings.judge_budget_max_seconds,
        concurrency=1,
    )
    own_hosts = [settings.public_backend_host] if settings.public_backend_host else []

    def make_target(config: EndpointConfig) -> HttpTarget:
        return HttpTarget(
            config,
            resolver=target_resolver or system_resolver,
            transport=target_transport,
            blocked_hosts=own_hosts,
        )

    run_deps = RunDeps(
        scan_store=scan_store,
        runner=TargetScanRunner(
            store=scan_store,
            judge=judge,
            judge_caps=judge_caps,
            clock=now,
            max_requests=settings.run_max_endpoint_requests,
            attacker=Attacker(
                Router(active_providers, clock=now),
                BudgetCaps(
                    requests=settings.attacker_budget_max_requests,
                    tokens=settings.attacker_budget_max_tokens,
                    seconds=settings.attacker_budget_max_seconds,
                    concurrency=1,
                ),
                now,
            ),
            max_turns=settings.multi_turn_max_turns,
        ),
        gate=gate,
        clock=now,
        catalog=catalog,
        make_target=make_target,
        judge_caps=judge_caps,
        judge_providers=[p.name for p in active_providers if p.configured],
        judge_prompt_version=PROMPT_VERSION,
    )
    app.include_router(
        build_setup_router(
            settings,
            SetupStore(engine, clock=now),
            setup_llm,
            run_deps,
            transport=target_transport,
            resolver=target_resolver,
            blocked_hosts=own_hosts,
        )
    )

    @app.get("/health")
    def health() -> JSONResponse:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            status_code, status, database = 200, "ok", "ok"
        except SQLAlchemyError:
            status_code, status, database = 503, "degraded", "error"
        return JSONResponse(
            status_code=status_code,
            content={
                "status": status,
                "database": database,
                "version": settings.app_version,
                "commit": settings.commit_sha,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    return app
