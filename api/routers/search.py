"""Search endpoints — search across collected items."""
from __future__ import annotations
import json
import os
import sqlite3
from fastapi import APIRouter, Query
from api.config import config

router = APIRouter()


def _ensure_db_exists() -> bool:
    """Check if the working DB exists (don't auto-create)."""
    return os.path.exists(config.DB_PATH)


@router.get("/search")
async def search_items(
    q: str = Query(default="", description="Search query (searches title + body)"),
    source: str | None = Query(default=None, description="Filter by source"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Full-text search across collected items in the working DB."""
    if not _ensure_db_exists():
        return {"items": [], "total": 0, "query": q, "message": "Database not yet created — run the pipeline first"}

    if not q and not source:
        return {"items": [], "total": 0, "query": q}

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row

    where_clauses = []
    params: list = []

    if q:
        where_clauses.append("(title LIKE ? OR body LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])

    if source:
        where_clauses.append("source = ?")
        params.append(source)

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    # Get total count
    count_sql = f"SELECT COUNT(*) AS c FROM items WHERE {where_sql}"
    total = conn.execute(count_sql, params).fetchone()["c"]

    # Get items
    sql = f"""SELECT id, source, source_name, title, url, body, author, published_at,
                     collected_at, score, sentiment, cluster_label, trend
              FROM items WHERE {where_sql}
              ORDER BY collected_at DESC LIMIT ? OFFSET ?"""
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    items = []
    for row in rows:
        item = dict(row)
        # Truncate body for search results
        if item.get("body"):
            item["body_excerpt"] = item["body"][:300]
            del item["body"]
        items.append(item)

    return {
        "items": items,
        "total": total,
        "query": q,
        "source_filter": source,
        "limit": limit,
        "offset": offset,
    }


@router.get("/search/sources")
async def list_sources():
    """List all sources in the database with item counts."""
    if not _ensure_db_exists():
        return {"sources": [], "total_sources": 0, "message": "Database not yet created"}
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT source, source_name, COUNT(*) AS count, MAX(collected_at) AS latest
           FROM items GROUP BY source, source_name ORDER BY count DESC"""
    ).fetchall()
    conn.close()
    return {
        "sources": [dict(r) for r in rows],
        "total_sources": len(rows),
    }
