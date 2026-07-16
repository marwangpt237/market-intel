"""Claims endpoints — validation engine claims + evidence."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from api.config import config
from validation.claim_store import ClaimStore

router = APIRouter()


def _get_store():
    return ClaimStore(config.DB_PATH)


@router.get("/claims")
async def list_claims(
    status: str | None = Query(default=None, description="Filter by validation status (VERIFIED, PROBABLE, HYPOTHESIS, CONFLICTED, EXPIRED, UNKNOWN)"),
    entity: str | None = Query(default=None, description="Filter by entity"),
    claim_type: str | None = Query(default=None, description="Filter by claim type"),
    limit: int = Query(default=50, ge=1, le=500),
):
    """List claims, optionally filtered by status, entity, or type."""
    store = _get_store()

    if status:
        claims = store.get_claims_by_status(status)
    elif entity:
        claims = store.get_claims_by_entity(entity)
    else:
        claims = store.get_all_claims(limit=limit)

    # Apply additional filters
    if claim_type:
        claims = [c for c in claims if c.claim_type == claim_type]

    # Limit
    claims = claims[:limit]

    return {
        "claims": [c.to_dict() for c in claims],
        "total": len(claims),
        "store_stats": store.get_stats(),
    }


@router.get("/claims/{claim_id}")
async def get_claim(claim_id: str):
    """Get a single claim by ID, including its evidence."""
    store = _get_store()
    claim = store.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim '{claim_id}' not found")

    evidence = store.get_evidence_for_claim(claim_id)
    version_history = store.get_version_history(claim_id)

    return {
        **claim.to_dict(),
        "evidence": evidence,
        "version_history": version_history,
    }


@router.get("/claims/stats/summary")
async def get_claims_stats():
    """Get aggregate stats about the claim store."""
    store = _get_store()
    return store.get_stats()


@router.get("/claims/status/{status}")
async def get_claims_by_status(status: str, limit: int = Query(default=50, ge=1, le=500)):
    """Get all claims with a specific validation status."""
    store = _get_store()
    claims = store.get_claims_by_status(status)[:limit]
    return {
        "claims": [c.to_dict() for c in claims],
        "total": len(claims),
        "status": status,
    }


@router.get("/entities/{entity}/claims")
async def get_claims_for_entity(entity: str):
    """Get all claims for a specific entity."""
    store = _get_store()
    claims = store.get_claims_by_entity(entity)
    return {
        "entity": entity,
        "claims": [c.to_dict() for c in claims],
        "total": len(claims),
    }
