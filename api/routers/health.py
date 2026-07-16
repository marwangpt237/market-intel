"""Health check endpoints."""
from __future__ import annotations
from fastapi import APIRouter
from api.config import config

router = APIRouter()


@router.get("/health")
async def health():
    """Basic health check — always returns 200 if the API is up."""
    return {
        "status": "ok",
        "service": config.API_TITLE,
        "version": config.API_VERSION,
    }


@router.get("/health/detailed")
async def health_detailed():
    """Detailed health — checks DB connectivity + reports dir."""
    import os
    checks: dict[str, str] = {}

    # Check DB
    try:
        import sqlite3
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute("SELECT 1")
        conn.close()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Check reports dir
    checks["reports_dir"] = "ok" if config.REPORTS_DIR.exists() else "missing"
    checks["data_dir"] = "ok" if config.DATA_DIR.exists() else "missing"

    # Check archive DB
    checks["archive_db"] = "ok" if os.path.exists(config.ARCHIVE_DB_PATH) else "not_yet_created"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}
