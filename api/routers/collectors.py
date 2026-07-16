"""Collectors endpoints — registry + health monitoring."""
from __future__ import annotations
import sqlite3
from fastapi import APIRouter, HTTPException, Query
from api.config import config

router = APIRouter()


def _get_registry():
    """Get the collector registry (triggers imports to register collectors)."""
    # Trigger imports — order matters
    import collectors.marketplace.ouedkniss_collector  # noqa: F401
    import collectors.marketplace.algeria_jobs_collector  # noqa: F401
    import collectors.marketplace.algeria_forum_collector  # noqa: F401
    import collectors.marketplace.algeria_gov_collector  # noqa: F401
    import collectors.marketplace.algeria_news_collector  # noqa: F401
    import collectors.marketplace.jumia_dz_collector  # noqa: F401
    import collectors.marketplace.algeria_realestate_collector  # noqa: F401
    import collectors.marketplace.algeria_tenders_collector  # noqa: F401
    from collectors.marketplace.base import CollectorRegistry
    return CollectorRegistry


@router.get("/collectors")
async def list_collectors(
    country: str | None = Query(default=None),
    category: str | None = Query(default=None),
):
    """List all registered collectors, optionally filtered by country or category."""
    registry = _get_registry()
    if country:
        collectors_list = registry.list_by_country(country)
    elif category:
        collectors_list = registry.list_by_category(category)
    else:
        collectors_list = registry.list_all()

    return {
        "collectors": [m.to_dict() for m in collectors_list],
        "total": len(collectors_list),
        "stats": registry.get_stats(),
    }


@router.get("/collectors/{name}")
async def get_collector(name: str):
    """Get metadata for a specific collector."""
    registry = _get_registry()
    collector = registry.get(name)
    if collector is None:
        raise HTTPException(status_code=404, detail=f"Collector '{name}' not found")
    return collector.metadata.to_dict()


@router.get("/collectors/stats/summary")
async def get_collectors_stats():
    """Get aggregate stats about the collector registry."""
    registry = _get_registry()
    return registry.get_stats()


@router.get("/collectors/health/all")
async def get_all_collectors_health():
    """Get health metrics for all collectors."""
    from collectors.marketplace.health import CollectorHealthMonitor
    monitor = CollectorHealthMonitor(config.DB_PATH)
    all_health = monitor.get_all_health()
    return {
        "collectors": {name: h.to_dict() for name, h in all_health.items()},
        "stats": monitor.get_stats(),
    }


@router.get("/collectors/health/{name}")
async def get_collector_health(name: str):
    """Get health metrics for a specific collector."""
    from collectors.marketplace.health import CollectorHealthMonitor
    monitor = CollectorHealthMonitor(config.DB_PATH)
    health = monitor.get_health(name)
    return health.to_dict()
