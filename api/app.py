"""
FastAPI App — Market-Intel production API.

Phase 1: Backend refactor. Preserves all existing architecture.
The app exposes REST endpoints while the underlying DailyRun workflow
remains unchanged.

Run:
    uvicorn api.app:app --reload
    uvicorn api.app:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure project root is on sys.path (so `core`, `collectors`, etc. importable)
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan: startup + shutdown hooks."""
    # Startup
    import logging
    logger = logging.getLogger("api")
    logger.info("Market-Intel API starting up")

    # Start the scheduler (Phase 2)
    try:
        from scheduler.engine import get_scheduler
        sched = get_scheduler()
        if not sched.is_running():
            sched.start()
            logger.info("Scheduler started (Phase 2)")
    except Exception as e:
        logger.error(f"Scheduler failed to start: {e}")

    yield

    # Shutdown
    logger.info("Market-Intel API shutting down")
    try:
        from scheduler.engine import get_scheduler
        sched = get_scheduler()
        if sched.is_running():
            sched.shutdown(wait=False)
            logger.info("Scheduler shut down")
    except Exception:
        pass


def create_app() -> FastAPI:
    """Create and configure the FastAPI app."""
    app = FastAPI(
        title=config.API_TITLE,
        description=config.API_DESCRIPTION,
        version=config.API_VERSION,
        lifespan=lifespan,
    )

    # CORS — allow dashboard + dev origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    from api.routers import health, runs, reports, collectors, claims, decisions, search, stats, scheduler

    app.include_router(health.router, prefix=config.API_PREFIX, tags=["health"])
    app.include_router(runs.router, prefix=config.API_PREFIX, tags=["runs"])
    app.include_router(scheduler.router, prefix=config.API_PREFIX, tags=["scheduler"])
    app.include_router(reports.router, prefix=config.API_PREFIX, tags=["reports"])
    app.include_router(collectors.router, prefix=config.API_PREFIX, tags=["collectors"])
    app.include_router(claims.router, prefix=config.API_PREFIX, tags=["claims"])
    app.include_router(decisions.router, prefix=config.API_PREFIX, tags=["decisions"])
    app.include_router(search.router, prefix=config.API_PREFIX, tags=["search"])
    app.include_router(stats.router, prefix=config.API_PREFIX, tags=["stats"])

    # Root endpoint
    @app.get("/", tags=["root"])
    async def root():
        return {
            "name": config.API_TITLE,
            "version": config.API_VERSION,
            "docs": "/docs",
            "redoc": "/redoc",
            "openapi": "/openapi.json",
            "health": f"{config.API_PREFIX}/health",
        }

    return app


app = create_app()
