"""Entities endpoints — companies, products, people, topics."""
from __future__ import annotations
import json
import os
import sqlite3
from collections import Counter
from fastapi import APIRouter, HTTPException, Query
from api.config import config

router = APIRouter()


def _ensure_db() -> bool:
    return os.path.exists(config.DB_PATH)


def _safe_query(sql: str, params: tuple = ()) -> list:
    """Safely execute a DB query — returns [] on any error."""
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


@router.get("/entities")
async def list_entities(
    type: str | None = Query(default=None, description="Filter by entity type (company, product, person, topic)"),
    limit: int = Query(default=50, ge=1, le=500),
):
    """List all entities (companies, products, people, topics) with mention counts."""
    if not _ensure_db():
        return {"entities": [], "total": 0}

    rows = _safe_query("SELECT metadata FROM items LIMIT 10000")

    entities: Counter = Counter()
    entity_types: dict[str, Counter] = {"company": Counter(), "product": Counter(), "person": Counter(), "topic": Counter()}

    for row in rows:
        try:
            meta = json.loads(row["metadata"] or "{}")
            for company in meta.get("entities", {}).get("companies", []):
                entities[f"company:{company.lower()}"] += 1
                entity_types["company"][company.lower()] += 1
            for product in meta.get("entities", {}).get("products", []):
                entities[f"product:{product.lower()}"] += 1
                entity_types["product"][product.lower()] += 1
            for person in meta.get("entities", {}).get("people", []):
                entities[f"person:{person.lower()}"] += 1
                entity_types["person"][person.lower()] += 1
            cluster = meta.get("cluster_label")
            if cluster and cluster != "uncategorized":
                entities[f"topic:{cluster.lower()}"] += 1
                entity_types["topic"][cluster.lower()] += 1
        except Exception:
            continue

    if type and type in entity_types:
        result = [{"entity": k, "type": type, "mentions": v} for k, v in entity_types[type].most_common(limit)]
    else:
        result = [{"entity": k.split(":", 1)[1] if ":" in k else k, "type": k.split(":", 1)[0] if ":" in k else "unknown", "mentions": v} for k, v in entities.most_common(limit)]

    return {"entities": result, "total": len(result)}


@router.get("/entities/companies")
async def list_companies(limit: int = Query(default=50, ge=1, le=500)):
    """List all companies with mention counts."""
    if not _ensure_db():
        return {"companies": [], "total": 0}
    rows = _safe_query("SELECT metadata FROM items LIMIT 10000")

    companies: Counter = Counter()
    for row in rows:
        try:
            meta = json.loads(row["metadata"] or "{}")
            for c in meta.get("entities", {}).get("companies", []):
                companies[c.lower()] += 1
        except Exception:
            continue

    result = [{"name": k, "mentions": v} for k, v in companies.most_common(limit)]
    return {"companies": result, "total": len(result)}


@router.get("/entities/products")
async def list_products(limit: int = Query(default=50, ge=1, le=500)):
    """List all products with mention counts."""
    if not _ensure_db():
        return {"products": [], "total": 0}
    rows = _safe_query("SELECT metadata FROM items LIMIT 10000")

    products: Counter = Counter()
    for row in rows:
        try:
            meta = json.loads(row["metadata"] or "{}")
            # From entity extraction
            for p in meta.get("entities", {}).get("products", []):
                products[p.lower()] += 1
            # From Algeria Pack
            for p in meta.get("algeria", {}).get("products", []):
                cat = p.get("category", "unknown")
                products[cat] += 1
        except Exception:
            continue

    result = [{"category": k, "mentions": v} for k, v in products.most_common(limit)]
    return {"products": result, "total": len(result)}


@router.get("/entities/topics")
async def list_topics(limit: int = Query(default=50, ge=1, le=500)):
    """List all topics (cluster labels) with mention counts + trends."""
    if not _ensure_db():
        return {"topics": [], "total": 0}
    rows = _safe_query("SELECT metadata FROM items LIMIT 10000")

    topics: Counter = Counter()
    topic_trends: dict[str, Counter] = {}
    for row in rows:
        try:
            meta = json.loads(row["metadata"] or "{}")
            cluster = meta.get("cluster_label")
            trend = meta.get("trend", "stable")
            if cluster and cluster != "uncategorized":
                topics[cluster] += 1
                if cluster not in topic_trends:
                    topic_trends[cluster] = Counter()
                topic_trends[cluster][trend] += 1
        except Exception:
            continue

    result = []
    for topic, count in topics.most_common(limit):
        trends = topic_trends.get(topic, Counter())
        dominant_trend = trends.most_common(1)[0][0] if trends else "stable"
        result.append({"topic": topic, "mentions": count, "dominant_trend": dominant_trend, "trend_distribution": dict(trends)})

    return {"topics": result, "total": len(result)}


@router.get("/entities/{entity_type}/{entity_name}")
async def get_entity(entity_type: str, entity_name: str):
    """Get details for a specific entity — mentions, claims, trends."""
    entity_name = entity_name.lower()
    entity_key = f"{entity_type}:{entity_name}"

    # Get claims for this entity
    try:
        from validation.claim_store import ClaimStore
        store = ClaimStore(config.DB_PATH)
        claims = store.get_claims_by_entity(entity_key)
    except Exception:
        claims = []

    return {
        "entity_type": entity_type,
        "entity_name": entity_name,
        "entity_key": entity_key,
        "claims": [c.to_dict() for c in claims],
        "claims_count": len(claims),
    }

