"""Knowledge Graph + Evidence endpoints."""
from __future__ import annotations
import json
import os
import sqlite3
from fastapi import APIRouter, HTTPException, Query
from api.config import config

router = APIRouter()


def _ensure_db() -> bool:
    return os.path.exists(config.DB_PATH)


@router.get("/knowledge-graph")
async def get_knowledge_graph(limit: int = Query(default=100, ge=1, le=1000)):
    """Get the entity graph (nodes + edges)."""
    if not _ensure_db():
        return {"nodes": [], "edges": [], "stats": {}}

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT metadata FROM items LIMIT 10000").fetchall()
    conn.close()

    # Find the item with _entity_graph
    graph_data = None
    for row in rows:
        try:
            meta = json.loads(row["metadata"] or "{}")
            if "_entity_graph" in meta:
                graph_data = meta["_entity_graph"]
                break
        except Exception:
            continue

    if not graph_data:
        return {"nodes": [], "edges": [], "stats": {"total_nodes": 0, "total_edges": 0}, "message": "No entity graph found in items"}

    # Truncate for API response
    nodes = graph_data.get("nodes", [])[:limit]
    edges = graph_data.get("edges", [])[:limit * 2]

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": graph_data.get("stats", {}),
    }


@router.get("/knowledge-graph/stats")
async def get_knowledge_graph_stats():
    """Get knowledge graph stats only (no nodes/edges)."""
    if not _ensure_db():
        return {"stats": {}}

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT metadata FROM items LIMIT 10000").fetchall()
    conn.close()

    for row in rows:
        try:
            meta = json.loads(row["metadata"] or "{}")
            if "_entity_graph" in meta:
                return {"stats": meta["_entity_graph"].get("stats", {})}
        except Exception:
            continue

    return {"stats": {}}


@router.get("/evidence")
async def list_evidence(
    claim_id: str | None = Query(default=None, description="Filter by claim ID"),
    source_id: str | None = Query(default=None, description="Filter by source ID"),
    limit: int = Query(default=50, ge=1, le=500),
):
    """List evidence pieces, optionally filtered by claim or source."""
    try:
        from validation.claim_store import ClaimStore
        store = ClaimStore(config.DB_PATH)

        if claim_id:
            evidence = store.get_evidence_for_claim(claim_id)
            return {"evidence": evidence[:limit], "total": len(evidence), "claim_id": claim_id}

        # Otherwise, scan all claims' evidence (limited)
        all_claims = store.get_all_claims(limit=100)
        all_evidence: list[dict] = []
        for claim in all_claims:
            ev = store.get_evidence_for_claim(claim.id)
            for e in ev:
                if source_id and e.get("source_id") != source_id:
                    continue
                all_evidence.append({**e, "claim_id": claim.id, "claim_entity": claim.entity, "claim_type": claim.claim_type})
                if len(all_evidence) >= limit:
                    break
            if len(all_evidence) >= limit:
                break

        return {"evidence": all_evidence, "total": len(all_evidence)}
    except Exception as e:
        return {"evidence": [], "total": 0, "error": str(e)}


@router.get("/evidence/claim/{claim_id}")
async def get_evidence_for_claim(claim_id: str):
    """Get all evidence for a specific claim."""
    try:
        from validation.claim_store import ClaimStore
        store = ClaimStore(config.DB_PATH)
        evidence = store.get_evidence_for_claim(claim_id)
        return {"claim_id": claim_id, "evidence": evidence, "total": len(evidence)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

