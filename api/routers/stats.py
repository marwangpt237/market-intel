"""Stats endpoints — dashboard metrics + moat metrics."""
from __future__ import annotations
import json
import sqlite3
from fastapi import APIRouter
from api.config import config

router = APIRouter()


@router.get("/stats/dashboard")
async def get_dashboard_metrics():
    """Get dashboard metrics — high-level numbers for the UI.

    Combines data from: working DB, archive DB, claim store, decision ledger,
    collector registry, health monitor.
    """
    metrics: dict = {}

    # Working DB stats
    try:
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row

        items_count = conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"]
        sources_count = conn.execute("SELECT COUNT(DISTINCT source) AS c FROM items").fetchone()["c"]

        # Items per source
        sources = conn.execute(
            "SELECT source, COUNT(*) AS c FROM items GROUP BY source ORDER BY c DESC LIMIT 10"
        ).fetchall()

        # Items per day (last 7)
        daily = conn.execute(
            """SELECT DATE(collected_at) AS date, COUNT(*) AS count
               FROM items WHERE collected_at > datetime('now', '-7 days')
               GROUP BY DATE(collected_at) ORDER BY date DESC"""
        ).fetchall()

        conn.close()

        metrics["items"] = {
            "total": items_count,
            "distinct_sources": sources_count,
            "top_sources": [dict(r) for r in sources],
            "daily_last_7": [dict(r) for r in daily],
        }
    except Exception as e:
        metrics["items"] = {"error": str(e)}

    # Archive stats
    try:
        from storage.raw_archiver import RawDataArchiver
        archiver = RawDataArchiver(config.ARCHIVE_DB_PATH)
        metrics["archive"] = archiver.get_stats()
    except Exception as e:
        metrics["archive"] = {"error": str(e)}

    # Claims stats
    try:
        from validation.claim_store import ClaimStore
        store = ClaimStore(config.DB_PATH)
        metrics["claims"] = store.get_stats()
    except Exception as e:
        metrics["claims"] = {"error": str(e)}

    # Decision ledger stats
    try:
        from validation.decision_ledger import DecisionLedger
        ledger = DecisionLedger(config.DB_PATH)
        metrics["decisions"] = ledger.get_stats()
    except Exception as e:
        metrics["decisions"] = {"error": str(e)}

    # Collectors
    try:
        # Trigger imports
        import collectors.marketplace.ouedkniss_collector  # noqa
        import collectors.marketplace.algeria_jobs_collector  # noqa
        import collectors.marketplace.algeria_forum_collector  # noqa
        import collectors.marketplace.algeria_gov_collector  # noqa
        import collectors.marketplace.algeria_news_collector  # noqa
        import collectors.marketplace.jumia_dz_collector  # noqa
        import collectors.marketplace.algeria_realestate_collector  # noqa
        import collectors.marketplace.algeria_tenders_collector  # noqa
        from collectors.marketplace.base import CollectorRegistry
        metrics["collectors"] = CollectorRegistry.get_stats()
    except Exception as e:
        metrics["collectors"] = {"error": str(e)}

    # Collector health
    try:
        from collectors.marketplace.health import CollectorHealthMonitor
        monitor = CollectorHealthMonitor(config.DB_PATH)
        metrics["collector_health"] = monitor.get_stats()
    except Exception as e:
        metrics["collector_health"] = {"error": str(e)}

    return metrics


@router.get("/stats/moat")
async def get_moat_metrics():
    """Get moat metrics — the 7 investor questions."""
    # Reuse the Moat Metrics Report logic but return as JSON
    try:
        from reports.moat_metrics_report import MoatMetricsReportGenerator
        # Generate to a temp file, read it back
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = MoatMetricsReportGenerator({
                "output_path": tmpdir,
                "storage": {"path": config.DB_PATH, "archive_path": config.ARCHIVE_DB_PATH},
            })
            # The generator needs items list — pass empty (it gathers from DB)
            from core.models import RawItem, ProcessedItem
            empty_item = ProcessedItem.from_raw(RawItem.create(
                source="api", source_name="API", title="moat", url="http://api"
            ))
            report_path = gen.generate([empty_item], "api_moat")
            content = open(report_path).read()
            return {
                "report_markdown": content,
                "report_path": report_path,
            }
    except Exception as e:
        return {"error": str(e)}


@router.get("/stats/archive")
async def get_archive_stats():
    """Get archive stats (total items, sources, date range)."""
    try:
        from storage.raw_archiver import RawDataArchiver
        archiver = RawDataArchiver(config.ARCHIVE_DB_PATH)
        return archiver.get_stats()
    except Exception as e:
        return {"error": str(e)}


@router.get("/stats/db")
async def get_db_stats():
    """Get working DB stats (items table)."""
    try:
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row

        total = conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"]
        distinct_sources = conn.execute("SELECT COUNT(DISTINCT source) AS c FROM items").fetchone()["c"]

        # Sentiment distribution
        sentiment_rows = conn.execute(
            "SELECT sentiment, COUNT(*) AS c FROM items GROUP BY sentiment"
        ).fetchall()

        # Date range
        date_range = conn.execute(
            "SELECT MIN(collected_at) AS min_d, MAX(collected_at) AS max_d FROM items"
        ).fetchone()

        conn.close()

        return {
            "total_items": total,
            "distinct_sources": distinct_sources,
            "sentiment_distribution": {r["sentiment"]: r["c"] for r in sentiment_rows},
            "earliest_collected": date_range["min_d"],
            "latest_collected": date_range["max_d"],
        }
    except Exception as e:
        return {"error": str(e)}
