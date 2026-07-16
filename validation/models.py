"""
Evidence Validation Engine — Phase 8 core subsystem.

No fact, metric, recommendation, score, trend, or confidence value enters
the knowledge base unless evaluated by this engine.

Every claim becomes a first-class object:

    {
      id: "clm_abc123",
      entity: "product:backpack",
      claim_type: "average_price",
      value: 4200,
      value_unit: "DZD",
      sources: ["aps.dz", "tsa-algerie.com"],
      evidence_count: 5,
      first_seen: "2026-07-15T...",
      last_seen: "2026-07-16T...",
      last_verified: "2026-07-16T...",
      supporting_evidence: [Evidence, ...],
      contradicting_evidence: [Evidence, ...],
      confidence_score: 0.78,
      validation_status: "PROBABLE",
      expiration_date: "2026-08-15T...",
      version_history: [
        {ts, status, confidence, reason}
      ]
    }

Validation rules:
  - Configurable minimum independent sources (default: 2)
  - Source reliability weights (TrustLayer)
  - Contradiction detection (claim value differs beyond tolerance)
  - Confidence decays over time (stale claims downgraded)
  - Auto-request new collection when confidence drops below threshold

Subsystem modules:
  models.py            — Claim, Evidence, ValidationStatus
  claim_store.py       — SQLite persistence
  claim_extractor.py   — converts processor outputs to Claim objects
  trust_layer.py       — source reliability registry
  evidence_validator.py — applies validation rules
  decision_ledger.py   — append-only log of decisions + claim IDs
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any


class ValidationStatus(str, Enum):
    """Validation status of a claim.

    Progression:
      UNKNOWN → HYPOTHESIS → PROBABLE → VERIFIED
                 ↓             ↓
              CONFLICTED    EXPIRED (when stale)
    """
    VERIFIED = "VERIFIED"          # Strong evidence, multiple sources, recent
    PROBABLE = "PROBABLE"          # Good evidence but not yet verified
    HYPOTHESIS = "HYPOTHESIS"      # Single source or low confidence
    CONFLICTED = "CONFLICTED"      # Contradicting evidence present
    EXPIRED = "EXPIRED"            # Stale — not seen recently
    UNKNOWN = "UNKNOWN"            # No evidence yet (should not happen post-validation)


class ClaimType(str, Enum):
    """Type of claim being made."""
    # Product-level
    AVERAGE_PRICE = "average_price"
    PRICE_RANGE = "price_range"
    DEMAND_LEVEL = "demand_level"
    SATURATION_LEVEL = "saturation_level"
    OPPORTUNITY_SCORE = "opportunity_score"
    TREND = "trend"
    TOP_COMPLAINT = "top_complaint"
    BEST_POSTING_HOURS = "best_posting_hours"
    RECOMMENDED_OFFER = "recommended_offer"
    STOCK_STATUS = "stock_status"

    # Entity-level
    ENTITY_MENTION = "entity_mention"
    PAIN_POINT = "pain_point"
    BUYING_SIGNAL = "buying_signal"
    COMPETITOR_MENTION = "competitor_mention"

    # Decision-level
    DECISION_ROI = "decision_roi"
    PROJECTED_OUTCOME = "projected_outcome"

    # Geographic
    WILAYA_DEMAND = "wilaya_demand"

    # Seasonal
    SEASONAL_SIGNAL = "seasonal_signal"

    # Generic
    METRIC = "metric"


@dataclass
class Evidence:
    """A single piece of evidence supporting or contradicting a claim."""
    source_id: str                  # e.g. "aps.dz", "reddit:r/algeria"
    source_type: str                # e.g. "rss", "reddit", "hacker_news"
    source_reliability: float       # 0.0 - 1.0 (from TrustLayer)
    value: Any                      # The value this source claims
    item_id: str | None = None      # Reference to the ProcessedItem
    item_url: str | None = None
    item_title: str | None = None
    collected_at: str | None = None # ISO timestamp
    supports: bool = True           # True = supports claim, False = contradicts
    confidence: float = 1.0         # 0-1 confidence in this evidence

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Claim:
    """A first-class claim object in the knowledge base.

    Every fact, metric, recommendation, score, trend, or confidence value
    in the platform is represented as a Claim.
    """
    id: str                                  # Stable hash-based ID
    entity: str                              # e.g. "product:backpack", "wilaya:DZ-16"
    claim_type: str                          # ClaimType value
    value: Any                               # The claimed value (number, string, list, etc.)
    value_unit: str | None = None            # "DZD", "count", "%", etc.

    sources: list[str] = field(default_factory=list)
    evidence_count: int = 0
    first_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_verified: str | None = None
    supporting_evidence: list[dict] = field(default_factory=list)
    contradicting_evidence: list[dict] = field(default_factory=list)

    confidence_score: float = 0.0            # 0.0 - 1.0
    validation_status: str = ValidationStatus.UNKNOWN.value
    expiration_date: str | None = None       # Auto-set based on claim_type

    version_history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Claim":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ─── Defaults ─────────────────────────────────────────────────────────────

# How long each claim type is considered fresh (in days)
CLAIM_FRESHNESS_DAYS: dict[str, int] = {
    ClaimType.AVERAGE_PRICE.value: 14,         # prices change fast
    ClaimType.PRICE_RANGE.value: 14,
    ClaimType.DEMAND_LEVEL.value: 7,
    ClaimType.SATURATION_LEVEL.value: 14,
    ClaimType.OPPORTUNITY_SCORE.value: 7,
    ClaimType.TREND.value: 3,                  # trends change very fast
    ClaimType.TOP_COMPLAINT.value: 30,
    ClaimType.BEST_POSTING_HOURS.value: 30,
    ClaimType.RECOMMENDED_OFFER.value: 14,
    ClaimType.STOCK_STATUS.value: 3,           # stock changes daily
    ClaimType.ENTITY_MENTION.value: 30,
    ClaimType.PAIN_POINT.value: 30,
    ClaimType.BUYING_SIGNAL.value: 7,
    ClaimType.COMPETITOR_MENTION.value: 14,
    ClaimType.DECISION_ROI.value: 7,
    ClaimType.PROJECTED_OUTCOME.value: 30,
    ClaimType.WILAYA_DEMAND.value: 14,
    ClaimType.SEASONAL_SIGNAL.value: 60,       # seasonal patterns are slow-moving
    ClaimType.METRIC.value: 14,
}

# Confidence thresholds (0-1)
CONFIDENCE_VERIFIED = 0.70      # >= → VERIFIED
CONFIDENCE_PROBABLE = 0.40      # >= → PROBABLE
CONFIDENCE_HYPOTHESIS = 0.10    # >= → HYPOTHESIS
# Below HYPOTHESIS threshold → UNKNOWN (shouldn't happen post-validation)

# Tolerance for value comparison (when checking for contradictions)
# Two values are "contradicting" if they differ by more than this ratio
CONTRADICTION_TOLERANCE = 0.30  # 30% difference → contradiction


def compute_claim_id(entity: str, claim_type: str, value: Any) -> str:
    """Stable hash ID for a claim.

    Two claims with same entity + type + value get the same ID
    (so they merge across runs).
    """
    import hashlib
    value_str = str(value) if not isinstance(value, (list, dict)) else str(sorted(value.items()) if isinstance(value, dict) else sorted(value))
    id_source = f"{entity}|{claim_type}|{value_str}"
    return "clm_" + hashlib.sha1(id_source.encode("utf-8")).hexdigest()[:12]


def compute_expiration_date(claim_type: str, last_seen: str | None = None) -> str:
    """Compute when a claim expires based on its type."""
    days = CLAIM_FRESHNESS_DAYS.get(claim_type, 14)
    base = datetime.fromisoformat(last_seen) if last_seen else datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    expiry = base + timedelta(days=days)
    return expiry.isoformat()
