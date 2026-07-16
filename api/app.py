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

from fastapi import FastAPI, Request
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

    # Phase 7: Audit logging middleware
    @app.middleware("http")
    async def audit_log_middleware(request: Request, call_next):
        import time
        start = time.time()

        # Extract API key if present
        from api.auth import is_auth_enabled, validate_api_key, record_audit_log
        auth_header = request.headers.get("Authorization", "")
        api_key = None
        if auth_header.startswith("Bearer "):
            raw_key = auth_header[7:]
            api_key = validate_api_key(raw_key)

        response = await call_next(request)
        duration_ms = (time.time() - start) * 1000

        # Record audit log for all requests
        record_audit_log(
            api_key_id=api_key.key_id if api_key else None,
            organization=api_key.organization if api_key else None,
            method=request.method,
            path=str(request.url.path),
            status_code=response.status_code,
            duration_ms=duration_ms,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

        return response

    # Register routers
    from api.routers import health, runs, reports, collectors, claims, decisions, search, stats, scheduler, entities, trends, knowledge_graph, static

    app.include_router(health.router, prefix=config.API_PREFIX, tags=["health"])
    app.include_router(runs.router, prefix=config.API_PREFIX, tags=["runs"])
    app.include_router(scheduler.router, prefix=config.API_PREFIX, tags=["scheduler"])
    app.include_router(reports.router, prefix=config.API_PREFIX, tags=["reports"])
    app.include_router(collectors.router, prefix=config.API_PREFIX, tags=["collectors"])
    app.include_router(claims.router, prefix=config.API_PREFIX, tags=["claims"])
    app.include_router(decisions.router, prefix=config.API_PREFIX, tags=["decisions"])
    app.include_router(knowledge_graph.router, prefix=config.API_PREFIX, tags=["knowledge_graph"])
    app.include_router(entities.router, prefix=config.API_PREFIX, tags=["entities"])
    app.include_router(trends.router, prefix=config.API_PREFIX, tags=["trends"])
    app.include_router(search.router, prefix=config.API_PREFIX, tags=["search"])
    app.include_router(stats.router, prefix=config.API_PREFIX, tags=["stats"])
    # Dashboard (no API prefix — served at /dashboard)
    app.include_router(static.router, tags=["dashboard"])

    # Phase 7: Auth + admin endpoints
    from api.routers import auth as auth_router
    app.include_router(auth_router.router, prefix=config.API_PREFIX, tags=["auth"])

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
