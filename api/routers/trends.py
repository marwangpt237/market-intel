"""Trends + Opportunities endpoints."""
from __future__ import annotations
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import os
import sqlite3
from fastapi import APIRouter, Query
from api.config import config

router = APIRouter()


def _ensure_db() -> bool:
    return os.path.exists(config.DB_PATH)


def _safe_query(sql: str, params: tuple = ()) -> list:
    if not _ensure_db():
        return []
    try:
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows
    except Exception:
        return []


@router.get("/trends")
async def list_trends(limit: int = Query(default=20, ge=1, le=100)):
    """List all detected trends (topics with trend != stable)."""
    if not _ensure_db():
        return {"trends": [], "total": 0}

    rows = _safe_query("SELECT metadata FROM items LIMIT 10000")

    trends: dict[str, dict] = defaultdict(lambda: {"count": 0, "trend": "stable", "items": []})
    for row in rows:
        try:
            meta = json.loads(row["metadata"] or "{}")
            cluster = meta.get("cluster_label", "")
            trend = meta.get("trend", "stable")
            if cluster and cluster != "uncategorized" and trend != "stable":
                trends[cluster]["count"] += 1
                trends[cluster]["trend"] = trend
                if len(trends[cluster]["items"]) < 3:
                    trends[cluster]["items"].append({
                        "title": meta.get("title", "")[:100],
                        "url": meta.get("url", ""),
                    })
        except Exception:
            continue

    # Sort by count
    result = sorted(
        [{"topic": k, **v} for k, v in trends.items()],
        key=lambda x: -x["count"]
    )[:limit]

    return {"trends": result, "total": len(result)}


@router.get("/trends/hot")
async def list_hot_trends(limit: int = Query(default=10, ge=1, le=50)):
    """List hot trends (trend = 'hot')."""
    if not _ensure_db():
        return {"trends": [], "total": 0}

    rows = _safe_query("SELECT metadata FROM items LIMIT 10000")

    hot: Counter = Counter()
    for row in rows:
        try:
            meta = json.loads(row["metadata"] or "{}")
            cluster = meta.get("cluster_label", "")
            trend = meta.get("trend", "stable")
            if cluster and trend == "hot":
                hot[cluster] += 1
        except Exception:
            continue

    result = [{"topic": k, "mentions": v, "trend": "hot"} for k, v in hot.most_common(limit)]
    return {"trends": result, "total": len(result)}


@router.get("/trends/rising")
async def list_rising_trends(limit: int = Query(default=10, ge=1, le=50)):
    """List rising trends (trend = 'rising' or 'emerging')."""
    if not _ensure_db():
        return {"trends": [], "total": 0}

    rows = _safe_query("SELECT metadata FROM items LIMIT 10000")

    rising: Counter = Counter()
    for row in rows:
        try:
            meta = json.loads(row["metadata"] or "{}")
            cluster = meta.get("cluster_label", "")
            trend = meta.get("trend", "stable")
            if cluster and trend in ("rising", "emerging"):
                rising[cluster] += 1
        except Exception:
            continue

    result = [{"topic": k, "mentions": v} for k, v in rising.most_common(limit)]
    return {"trends": result, "total": len(result)}


@router.get("/opportunities")
async def list_opportunities(limit: int = Query(default=20, ge=1, le=100)):
    """List opportunities — high opportunity scores from product intelligence."""
    if not _ensure_db():
        return {"opportunities": [], "total": 0}

    # Look for _product_intelligence in items metadata
    rows = _safe_query("SELECT metadata FROM items LIMIT 10000")

    opportunities: list[dict] = []
    for row in rows:
        try:
            meta = json.loads(row["metadata"] or "{}")
            product_intel = meta.get("_product_intelligence", {})
            for product in product_intel.get("products", []):
                opportunities.append({
                    "product": product.get("product", ""),
                    "category": product.get("category", ""),
                    "opportunity_score": product.get("opportunity_score", 0),
                    "demand": product.get("demand", ""),
                    "saturation": product.get("saturation", ""),
                    "avg_price_dzd": product.get("average_selling_price_dzd"),
                    "top_wilayas": product.get("highest_demand_wilayas", []),
                    "recommended_offer": product.get("recommended_offer", ""),
                })
        except Exception:
            continue

    # Sort by opportunity score
    opportunities.sort(key=lambda x: -x.get("opportunity_score", 0))
    opportunities = opportunities[:limit]

    return {"opportunities": opportunities, "total": len(opportunities)}


@router.get("/opportunities/top")
async def list_top_opportunities(limit: int = Query(default=10, ge=1, le=50)):
    """List top opportunities (opportunity score >= 50)."""
    if not _ensure_db():
        return {"opportunities": [], "total": 0}

    rows = _safe_query("SELECT metadata FROM items LIMIT 10000")

    opportunities: list[dict] = []
    for row in rows:
        try:
            meta = json.loads(row["metadata"] or "{}")
            product_intel = meta.get("_product_intelligence", {})
            for product in product_intel.get("products", []):
                score = product.get("opportunity_score", 0)
                if score >= 50:
                    opportunities.append({
                        "product": product.get("product", ""),
                        "category": product.get("category", ""),
                        "opportunity_score": score,
                        "demand": product.get("demand", ""),
                        "saturation": product.get("saturation", ""),
                    })
        except Exception:
            continue

    opportunities.sort(key=lambda x: -x.get("opportunity_score", 0))
    return {"opportunities": opportunities[:limit], "total": len(opportunities)}


@router.get("/trends/timeline")
async def get_trends_timeline(days: int = Query(default=7, ge=1, le=90)):
    """Get trends over time — items per day for last N days."""
    if not _ensure_db():
        return {"timeline": [], "days": days}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = _safe_query(
        """SELECT DATE(collected_at) AS date, COUNT(*) AS count, source
           FROM items WHERE collected_at > ?
           GROUP BY DATE(collected_at), source
           ORDER BY date DESC""",
        (cutoff,)
    )

    # Group by date
    timeline: dict[str, dict] = defaultdict(lambda: {"total": 0, "by_source": {}})
    for row in rows:
        date = row["date"]
        timeline[date]["total"] += row["count"]
        timeline[date]["by_source"][row["source"]] = row["count"]

    result = [{"date": k, "total": v["total"], "by_source": v["by_source"]} for k, v in sorted(timeline.items())]
    return {"timeline": result, "days": days}

