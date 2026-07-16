"""
Knowledge Gap Detector — aggregates missing-evidence requests from the
Validation Engine into structured gap categories.

The Validation Engine emits individual missing-evidence requests per claim.
This module groups them by:
  - Entity (multiple claims for the same entity = bigger gap)
  - Claim type (price gaps, demand gaps, trend gaps, etc.)
  - Source type needed (RSS, Reddit, HN, Marketplace, etc.)

Output: a list of KnowledgeGap objects, each with:
  - gap_id
  - entity (the entity lacking evidence)
  - gap_type (price, demand, trend, geographic, seasonal, etc.)
  - affected_claims (list of claim_ids)
  - current_confidence (avg of affected claims)
  - target_confidence (the confidence we want to reach)
  - confidence_delta (target - current)
  - priority (P0/P1/P2/P3 based on delta + claim count)
  - suggested_source_types (which collector types could fill the gap)
  - suggested_queries (specific search terms to use)
  - recommended_collection_hours (when to collect: 24h, 6h, 1h urgency)
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any
from core.logger import get_logger


# Gap type → suggested source types + query templates
_GAP_TYPE_STRATEGIES: dict[str, dict] = {
    "average_price": {
        "suggested_source_types": ["rss", "ouedkniss", "facebook_marketplace"],
        "suggested_query_templates": [
            "{entity_name} price DZD",
            "{entity_name} prix DA",
            "{entity_name} vendre",
            "{entity_name} ثمن",
        ],
        "collection_urgency_hours": 24,
    },
    "price_range": {
        "suggested_source_types": ["rss", "ouedkniss", "facebook_marketplace"],
        "suggested_query_templates": [
            "{entity_name} price range",
            "{entity_name} entre prix",
        ],
        "collection_urgency_hours": 24,
    },
    "demand_level": {
        "suggested_source_types": ["reddit", "rss", "google_news", "facebook_groups"],
        "suggested_query_templates": [
            "{entity_name} demand",
            "{entity_name} demande",
            "{entity_name} trend",
            "{entity_name} popular",
        ],
        "collection_urgency_hours": 12,
    },
    "saturation_level": {
        "suggested_source_types": ["ouedkniss", "facebook_marketplace", "rss"],
        "suggested_query_templates": [
            "{entity_name} sellers",
            "{entity_name} vendeurs",
            "{entity_name} competition",
        ],
        "collection_urgency_hours": 48,
    },
    "opportunity_score": {
        "suggested_source_types": ["reddit", "rss", "google_news"],
        "suggested_query_templates": [
            "{entity_name} opportunity",
            "{entity_name} market gap",
        ],
        "collection_urgency_hours": 24,
    },
    "trend": {
        "suggested_source_types": ["google_news", "rss", "hacker_news", "reddit"],
        "suggested_query_templates": [
            "{entity_name} trend 2026",
            "{entity_name} actualité",
            "{entity_name} news",
        ],
        "collection_urgency_hours": 6,  # trends are time-sensitive
    },
    "wilaya_demand": {
        "suggested_source_types": ["ouedkniss", "facebook_marketplace", "facebook_groups"],
        "suggested_query_templates": [
            "{entity_name} livraison wilaya",
            "{entity_name} delivery province",
        ],
        "collection_urgency_hours": 48,
    },
    "seasonal_signal": {
        "suggested_source_types": ["rss", "google_news"],
        "suggested_query_templates": [
            "{entity_name} Ramadan",
            "{entity_name} Aid",
            "{entity_name} seasonal",
        ],
        "collection_urgency_hours": 72,
    },
    "stock_status": {
        "suggested_source_types": ["ouedkniss", "facebook_marketplace"],
        "suggested_query_templates": [
            "{entity_name} stock",
            "{entity_name} disponible",
            "{entity_name} rupture",
        ],
        "collection_urgency_hours": 6,  # stock changes fast
    },
    "pain_point": {
        "suggested_source_types": ["reddit", "hacker_news"],
        "suggested_query_templates": [
            "{entity_name} complaint",
            "{entity_name} problem",
            "{entity_name} issue",
        ],
        "collection_urgency_hours": 48,
    },
    "buying_signal": {
        "suggested_source_types": ["reddit", "hacker_news", "job_boards"],
        "suggested_query_templates": [
            "{entity_name} looking for",
            "{entity_name} hiring",
            "{entity_name} need",
        ],
        "collection_urgency_hours": 12,
    },
    "entity_mention": {
        "suggested_source_types": ["rss", "google_news", "reddit"],
        "suggested_query_templates": [
            "{entity_name}",
            "{entity_name} mentioned",
        ],
        "collection_urgency_hours": 24,
    },
    "decision_roi": {
        "suggested_source_types": [],  # internal — no new collection helps
        "suggested_query_templates": [],
        "collection_urgency_hours": 0,
    },
    "projected_outcome": {
        "suggested_source_types": [],  # internal
        "suggested_query_templates": [],
        "collection_urgency_hours": 0,
    },
    "metric": {
        "suggested_source_types": ["rss", "google_news"],
        "suggested_query_templates": ["{entity_name}"],
        "collection_urgency_hours": 24,
    },
    "best_posting_hours": {
        "suggested_source_types": ["facebook_groups", "ouedkniss"],
        "suggested_query_templates": ["{entity_name}"],
        "collection_urgency_hours": 168,  # weekly is fine
    },
    "recommended_offer": {
        "suggested_source_types": ["facebook_groups", "reddit"],
        "suggested_query_templates": ["{entity_name} promo", "{entity_name} discount"],
        "collection_urgency_hours": 48,
    },
    "competitor_mention": {
        "suggested_source_types": ["rss", "google_news", "reddit"],
        "suggested_query_templates": ["{entity_name} competitor", "{entity_name} vs"],
        "collection_urgency_hours": 48,
    },
}

# Default for unknown claim types
_DEFAULT_STRATEGY = {
    "suggested_source_types": ["rss", "google_news"],
    "suggested_query_templates": ["{entity_name}"],
    "collection_urgency_hours": 24,
}


@dataclass
class KnowledgeGap:
    """A structured knowledge gap detected by the system."""
    gap_id: str
    entity: str
    entity_name: str                      # human-readable name for query templates
    gap_type: str                         # claim_type that's lacking evidence
    affected_claims: list[str]            # claim IDs affected
    affected_claim_count: int
    current_confidence: float             # avg confidence of affected claims
    target_confidence: float              # 0.70 for VERIFIED, 0.40 for PROBABLE
    confidence_delta: float               # target - current
    priority: str                         # P0/P1/P2/P3
    suggested_source_types: list[str]
    suggested_queries: list[str]
    collection_urgency_hours: int
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


class KnowledgeGapDetector:
    """Detects knowledge gaps from missing-evidence requests.

    Input: list of missing-evidence request dicts (from EvidenceValidator)
    Output: list of KnowledgeGap objects, sorted by priority
    """

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._logger = get_logger("knowledge_gap_detector")

    def detect_gaps(
        self,
        missing_evidence_requests: list[dict],
        existing_claims: list[dict] | None = None,
    ) -> list[KnowledgeGap]:
        """Detect knowledge gaps from missing-evidence requests.

        Args:
            missing_evidence_requests: list of dicts with claim_id, entity, claim_type,
                                       current_confidence, current_sources, needed_sources
            existing_claims: optional list of all claims (for context)

        Returns:
            List of KnowledgeGap objects, sorted by priority (P0 first)
        """
        if not missing_evidence_requests:
            return []

        # Group missing-evidence requests by (entity, claim_type)
        grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for req in missing_evidence_requests:
            entity = req.get("entity", "unknown")
            claim_type = req.get("claim_type", "unknown")
            grouped[(entity, claim_type)].append(req)

        # Build KnowledgeGap objects
        gaps: list[KnowledgeGap] = []
        for (entity, claim_type), requests in grouped.items():
            gap = self._build_gap(entity, claim_type, requests)
            if gap:
                gaps.append(gap)

        # Sort by priority (P0 first), then by confidence_delta (largest first)
        priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        gaps.sort(key=lambda g: (priority_order.get(g.priority, 4), -g.confidence_delta))

        self._logger.info(
            f"Knowledge gap detector: {len(gaps)} gaps detected "
            f"({sum(1 for g in gaps if g.priority == 'P0')} P0, "
            f"{sum(1 for g in gaps if g.priority == 'P1')} P1, "
            f"{sum(1 for g in gaps if g.priority == 'P2')} P2)"
        )
        return gaps

    def _build_gap(
        self,
        entity: str,
        claim_type: str,
        requests: list[dict],
    ) -> KnowledgeGap | None:
        """Build a single KnowledgeGap from grouped requests."""
        # Get strategy for this claim type
        strategy = _GAP_TYPE_STRATEGIES.get(claim_type, _DEFAULT_STRATEGY)

        # Aggregate confidence
        confidences = [r.get("current_confidence", 0) for r in requests]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0

        # Target confidence: 0.70 (VERIFIED) if we have any sources, else 0.40 (PROBABLE)
        target_confidence = 0.70 if any(r.get("current_sources", 0) > 0 for r in requests) else 0.40
        confidence_delta = target_confidence - avg_confidence

        # Determine priority
        priority = self._compute_priority(
            len(requests),
            confidence_delta,
            strategy.get("collection_urgency_hours", 24),
        )

        # Build entity name for query templates (strip prefixes like "product:", "wilaya:")
        entity_name = entity.split(":", 1)[-1] if ":" in entity else entity
        entity_name = entity_name.replace("_", " ").replace("-", " ")

        # Generate suggested queries
        suggested_queries = []
        for template in strategy.get("suggested_query_templates", []):
            suggested_queries.append(template.format(entity_name=entity_name))

        # Build gap ID
        import hashlib
        gap_id = "gap_" + hashlib.sha1(f"{entity}|{claim_type}".encode()).hexdigest()[:12]

        return KnowledgeGap(
            gap_id=gap_id,
            entity=entity,
            entity_name=entity_name,
            gap_type=claim_type,
            affected_claims=[r.get("claim_id", "") for r in requests],
            affected_claim_count=len(requests),
            current_confidence=round(avg_confidence, 3),
            target_confidence=target_confidence,
            confidence_delta=round(confidence_delta, 3),
            priority=priority,
            suggested_source_types=strategy.get("suggested_source_types", []),
            suggested_queries=suggested_queries,
            collection_urgency_hours=strategy.get("collection_urgency_hours", 24),
        )

    @staticmethod
    def _compute_priority(
        affected_count: int,
        confidence_delta: float,
        urgency_hours: int,
    ) -> str:
        """Compute priority based on affected claims, confidence delta, and urgency.

        P0: many affected claims AND large confidence gap AND high urgency
        P1: moderate affected claims OR large confidence gap
        P2: few affected claims OR small confidence gap
        P3: minimal impact
        """
        # Urgency multiplier (more urgent = higher priority)
        urgency_mult = 1.5 if urgency_hours <= 6 else 1.2 if urgency_hours <= 12 else 1.0

        # Score: weighted combination
        score = (affected_count * 0.3) + (confidence_delta * 0.5) + (urgency_mult - 1.0) * 2

        if score >= 1.5:
            return "P0"
        elif score >= 0.8:
            return "P1"
        elif score >= 0.3:
            return "P2"
        else:
            return "P3"
