from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from redflag_backend.llm.api import build_llm_router
from redflag_backend.llm.provider import Provider
from redflag_backend.settings import Settings


def create_app(
    settings: Settings,
    providers: Sequence[Provider] | None = None,
    clock: Callable[[], float] | None = None,
) -> FastAPI:
    app = FastAPI(title="Redflag")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["X-Owner-Token", "Content-Type"],
    )
    app.include_router(build_llm_router(settings, providers or [], clock))
    engine = create_engine(
        settings.database_url,
        connect_args={"connect_timeout": int(settings.db_timeout_seconds)},
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
