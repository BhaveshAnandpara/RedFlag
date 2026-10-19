import time
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from redflag_backend.llm.api import build_llm_router
from redflag_backend.llm.provider import Provider
from redflag_backend.llm.providers.factory import build_providers
from redflag_backend.sandbox.loader import BOTS_DIR, load_bots
from redflag_backend.scan.api import build_scan_router
from redflag_backend.scan.bot_models import bot_budget_caps, build_bot_providers, build_bot_router
from redflag_backend.scan.catalog import load_catalog
from redflag_backend.scan.runner import ScanRunner
from redflag_backend.scan.store import ScanStore
from redflag_backend.scan.suite import load_suite
from redflag_backend.settings import Settings


def create_app(
    settings: Settings,
    providers: Sequence[Provider] | None = None,
    clock: Callable[[], float] | None = None,
    bot_providers: Sequence[Provider] | None = None,
    bots_dir: Path | None = None,
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

    app = FastAPI(title="Redflag", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["X-Owner-Token", "Content-Type"],
    )
    active_providers = build_providers(settings) if providers is None else providers
    app.include_router(build_llm_router(settings, active_providers, engine, clock))

    # The demo bots have their own keys, router and budget, apart from Redflag's own router.
    active_bot_providers = (
        build_bot_providers(settings) if bot_providers is None else list(bot_providers)
    )
    catalog = load_catalog()
    runner = ScanRunner(
        store=scan_store,
        router=build_bot_router(active_bot_providers, now),
        caps=bot_budget_caps(settings),
        clock=now,
        suite=load_suite(),
        catalog=catalog,
    )
    app.include_router(
        build_scan_router(
            settings,
            scan_store,
            load_bots(bots_dir or BOTS_DIR),
            runner,
            active_bot_providers,
            catalog,
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
