"""Decisions endpoints — decision ledger."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from api.config import config
from validation.decision_ledger import DecisionLedger

router = APIRouter()


def _get_ledger():
    return DecisionLedger(config.DB_PATH)


@router.get("/decisions")
async def list_decisions(limit: int = Query(default=50, ge=1, le=500)):
    """List recent decisions from the ledger."""
    ledger = _get_ledger()
    decisions = ledger.get_recent_decisions(limit=limit)
    return {
        "decisions": decisions,
        "total": len(decisions),
        "stats": ledger.get_stats(),
    }


@router.get("/decisions/{decision_id}")
async def get_decision(decision_id: str):
    """Get a specific decision by ID."""
    ledger = _get_ledger()
    decision = ledger.get_decision(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail=f"Decision '{decision_id}' not found")
    return decision


@router.get("/decisions/warnings/list")
async def get_decisions_with_warnings(limit: int = Query(default=50, ge=1, le=500)):
    """Get decisions that have warnings (weak claims, conflicts, etc.)."""
    ledger = _get_ledger()
    decisions = ledger.get_decisions_with_warnings(limit=limit)
    return {
        "decisions": decisions,
        "total": len(decisions),
    }


@router.get("/decisions/low-confidence/list")
async def get_low_confidence_decisions(
    threshold: float = Query(default=0.40, ge=0.0, le=1.0),
    limit: int = Query(default=50, ge=1, le=500),
):
    """Get decisions with confidence below a threshold."""
    ledger = _get_ledger()
    decisions = ledger.get_low_confidence_decisions(threshold=threshold, limit=limit)
    return {
        "decisions": decisions,
        "total": len(decisions),
        "threshold": threshold,
    }


@router.get("/decisions/stats/summary")
async def get_decisions_stats():
    """Get aggregate stats about the decision ledger."""
    ledger = _get_ledger()
    return ledger.get_stats()
