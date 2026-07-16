"""
Evidence Validator — applies validation rules to claims.

Rules:
  1. Minimum independent sources: claim must have N independent sources
     (default 2) with reliability >= min_evidence_reliability (0.30)
     to reach PROBABLE status. N+1 independent sources → VERIFIED.

  2. Source reliability weighting: each source's evidence is weighted
     by its reliability from the TrustLayer.

  3. Contradiction detection: if any evidence contradicts the claim
     value (differs beyond tolerance), status → CONFLICTED.

  4. Confidence computation:
       confidence = Σ(reliability × evidence_confidence) / total_evidence
     Capped 0-1. Reduced by contradicting evidence.

  5. Staleness check: if last_seen > expiration_date → EXPIRED.

  6. Status transitions:
       UNKNOWN → HYPOTHESIS (1 source)
       HYPOTHESIS → PROBABLE (2+ independent sources, no contradictions)
       PROBABLE → VERIFIED (3+ independent sources, confidence >= 0.70)
       any → CONFLICTED (contradicting evidence)
       any → EXPIRED (stale)

  7. Missing evidence detection: if confidence drops below 0.40,
     emit a "missing_evidence" request for additional collection.

All rules are deterministic — no LLM required.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from core.logger import get_logger
from validation.models import (
    Claim, Evidence, ValidationStatus, ClaimType,
    CONFIDENCE_VERIFIED, CONFIDENCE_PROBABLE, CONFIDENCE_HYPOTHESIS,
    CONTRADICTION_TOLERANCE,
    compute_expiration_date,
)
from validation.trust_layer import TrustLayer
from validation.claim_store import ClaimStore


class EvidenceValidator:
    """Applies validation rules to claims.

    Usage:
        validator = EvidenceValidator(store, trust_layer)
        validator.validate_claim(claim, evidence_list)
        # claim.validation_status, claim.confidence_score updated
        # store updated
    """

    def __init__(
        self,
        store: ClaimStore,
        trust_layer: TrustLayer,
        config: dict | None = None,
    ):
        self._store = store
        self._trust_layer = trust_layer
        self._config = config or {}
        self._logger = get_logger("evidence_validator")

        # Configurable thresholds
        self._min_sources_probable: int = int(self._config.get("min_sources_probable", 2))
        self._min_sources_verified: int = int(self._config.get("min_sources_verified", 3))
        self._contradiction_tolerance: float = float(
            self._config.get("contradiction_tolerance", CONTRADICTION_TOLERANCE)
        )
        self._confidence_verified: float = float(self._config.get("confidence_verified", CONFIDENCE_VERIFIED))
        self._confidence_probable: float = float(self._config.get("confidence_probable", CONFIDENCE_PROBABLE))
        self._confidence_hypothesis: float = float(self._config.get("confidence_hypothesis", CONFIDENCE_HYPOTHESIS))

        # Track missing-evidence requests emitted this run
        self._missing_evidence_requests: list[dict] = []

    def validate_claim(self, claim: Claim, evidence: list[Evidence]) -> Claim:
        """Validate a claim given its evidence.

        Updates claim.confidence_score, claim.validation_status,
        claim.supporting_evidence, claim.contradicting_evidence,
        claim.expiration_date, claim.last_verified.

        Persists the claim + version history to the store.

        Returns the updated claim.
        """
        # Capture old state for version history
        old_status = claim.validation_status
        old_confidence = claim.confidence_score

        # Update last_seen to now
        now = datetime.now(timezone.utc).isoformat()
        claim.last_seen = now
        claim.last_verified = now

        # Reset evidence lists (will repopulate)
        claim.supporting_evidence = []
        claim.contradicting_evidence = []

        # Compute expiration date based on claim type
        claim.expiration_date = compute_expiration_date(claim.claim_type, claim.last_seen)

        # Separate supporting vs contradicting evidence
        for ev in evidence:
            ev_dict = ev.to_dict()
            if ev.supports:
                claim.supporting_evidence.append(ev_dict)
            else:
                claim.contradicting_evidence.append(ev_dict)

        # Count independent reliable sources
        reliable_sources: set[str] = set()
        for ev in evidence:
            if ev.supports and self._trust_layer.is_reliable_enough(ev.source_reliability):
                reliable_sources.add(ev.source_id)
        reliable_source_count = len(reliable_sources)

        # Update sources list + evidence count
        all_sources = list({ev.source_id for ev in evidence})
        claim.sources = all_sources
        claim.evidence_count = len(evidence)

        # Compute confidence
        confidence = self._compute_confidence(evidence, claim.value, claim.claim_type)
        claim.confidence_score = round(confidence, 3)

        # Determine validation status
        new_status = self._determine_status(
            claim,
            reliable_source_count,
            len(claim.contradicting_evidence),
            confidence,
        )

        # Check for staleness (overrides other statuses if expired)
        if self._is_stale(claim):
            new_status = ValidationStatus.EXPIRED

        claim.validation_status = new_status.value

        # Persist to store
        self._store.upsert_claim(claim)

        # Add evidence to store
        for ev in evidence:
            self._store.add_evidence(claim.id, ev)

        # Record version history if status or confidence changed
        if new_status.value != old_status or abs(confidence - old_confidence) > 0.01:
            reason = self._compute_status_change_reason(
                old_status, new_status.value, old_confidence, confidence,
                reliable_source_count, len(claim.contradicting_evidence)
            )
            self._store.add_version_history(
                claim_id=claim.id,
                old_status=old_status,
                new_status=new_status.value,
                old_confidence=old_confidence,
                new_confidence=confidence,
                reason=reason,
            )

        # Emit missing-evidence request if confidence is low OR if reliable source count is insufficient
        needs_more_sources = (
            reliable_source_count < self._min_sources_probable
            and new_status not in (ValidationStatus.CONFLICTED, ValidationStatus.EXPIRED)
        )
        if confidence < self._confidence_probable or needs_more_sources:
            self._missing_evidence_requests.append({
                "claim_id": claim.id,
                "entity": claim.entity,
                "claim_type": claim.claim_type,
                "current_confidence": confidence,
                "current_sources": reliable_source_count,
                "needed_sources": self._min_sources_probable,
                "request": f"Need {self._min_sources_probable - reliable_source_count} more independent source(s) for entity '{claim.entity}' claim '{claim.claim_type}'",
            })

        return claim

    def _compute_confidence(
        self,
        evidence: list[Evidence],
        claim_value: Any,
        claim_type: str,
    ) -> float:
        """Compute confidence score 0-1 for a claim given its evidence.

        Formula:
          supporting_weight = Σ(reliability × evidence_confidence) for supporting evidence
          contradicting_weight = Σ(reliability × evidence_confidence) for contradicting
          total = supporting_weight + contradicting_weight
          confidence = (supporting - contradicting) / total (if total > 0)

        Additional boost: source diversity (more unique sources → higher confidence)
        """
        if not evidence:
            return 0.0

        supporting_weight = 0.0
        contradicting_weight = 0.0
        supporting_sources: set[str] = set()
        contradicting_sources: set[str] = set()

        for ev in evidence:
            weight = ev.source_reliability * ev.confidence
            if ev.supports:
                supporting_weight += weight
                supporting_sources.add(ev.source_id)
            else:
                contradicting_weight += weight
                contradicting_sources.add(ev.source_id)

        total = supporting_weight + contradicting_weight
        if total == 0:
            return 0.0

        base_confidence = (supporting_weight - contradicting_weight) / total
        # Clamp to 0-1
        base_confidence = max(0.0, min(1.0, base_confidence))

        # Diversity bonus: more unique supporting sources → higher confidence
        # (diminishing returns — log scale)
        import math
        diversity_bonus = min(0.20, math.log10(max(1, len(supporting_sources))) * 0.10)

        # Contradiction penalty: more unique contradicting sources → lower confidence
        contradiction_penalty = min(0.40, len(contradicting_sources) * 0.15)

        final = base_confidence + diversity_bonus - contradiction_penalty
        return max(0.0, min(1.0, final))

    def _determine_status(
        self,
        claim: Claim,
        reliable_source_count: int,
        contradiction_count: int,
        confidence: float,
    ) -> ValidationStatus:
        """Determine validation status based on evidence + confidence."""
        # Contradiction → CONFLICTED (highest priority)
        if contradiction_count > 0:
            return ValidationStatus.CONFLICTED

        # Staleness check (done in _is_stale, but double-check here)
        if self._is_stale(claim):
            return ValidationStatus.EXPIRED

        # VERIFIED: 3+ reliable sources AND confidence >= 0.70
        if reliable_source_count >= self._min_sources_verified and confidence >= self._confidence_verified:
            return ValidationStatus.VERIFIED

        # PROBABLE: 2+ reliable sources AND confidence >= 0.40
        if reliable_source_count >= self._min_sources_probable and confidence >= self._confidence_probable:
            return ValidationStatus.PROBABLE

        # HYPOTHESIS: at least 1 source
        if reliable_source_count >= 1 or claim.evidence_count >= 1:
            return ValidationStatus.HYPOTHESIS

        return ValidationStatus.UNKNOWN

    @staticmethod
    def _is_stale(claim: Claim) -> bool:
        """Check if a claim is stale (last_seen > expiration_date)."""
        if not claim.expiration_date:
            return False
        try:
            now = datetime.now(timezone.utc)
            expiry = datetime.fromisoformat(claim.expiration_date)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            return now > expiry
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _compute_status_change_reason(
        old_status: str,
        new_status: str,
        old_confidence: float,
        new_confidence: float,
        source_count: int,
        contradiction_count: int,
    ) -> str:
        """Generate a human-readable reason for a status change."""
        reasons = []
        if old_status != new_status:
            reasons.append(f"status changed {old_status} → {new_status}")
        if abs(new_confidence - old_confidence) > 0.01:
            reasons.append(f"confidence {old_confidence:.2f} → {new_confidence:.2f}")
        reasons.append(f"{source_count} reliable sources, {contradiction_count} contradictions")
        return "; ".join(reasons)

    def detect_contradiction(
        self,
        claim_value: Any,
        evidence_value: Any,
        claim_type: str,
    ) -> bool:
        """Check if an evidence value contradicts a claim value.

        For numeric values: contradiction if |claim - evidence| / max(claim, evidence) > tolerance
        For strings: contradiction if values differ (case-insensitive)
        For lists: contradiction if sets are disjoint
        """
        if claim_value is None or evidence_value is None:
            return False

        # Numeric comparison
        if isinstance(claim_value, (int, float)) and isinstance(evidence_value, (int, float)):
            if claim_value == 0 and evidence_value == 0:
                return False
            max_val = max(abs(claim_value), abs(evidence_value))
            if max_val == 0:
                return False
            diff_ratio = abs(claim_value - evidence_value) / max_val
            return diff_ratio > self._contradiction_tolerance

        # String comparison
        if isinstance(claim_value, str) and isinstance(evidence_value, str):
            return claim_value.lower() != evidence_value.lower()

        # List comparison (sets disjoint = contradiction)
        if isinstance(claim_value, list) and isinstance(evidence_value, list):
            claim_set = {str(x).lower() for x in claim_value}
            evidence_set = {str(x).lower() for x in evidence_value}
            return claim_set.isdisjoint(evidence_set)

        # Dict comparison
        if isinstance(claim_value, dict) and isinstance(evidence_value, dict):
            return claim_value != evidence_value

        # Different types → contradiction
        return True

    def get_missing_evidence_requests(self) -> list[dict]:
        """Get the list of missing-evidence requests emitted this run."""
        return self._missing_evidence_requests

    def clear_missing_evidence_requests(self) -> None:
        """Clear the missing-evidence requests (call at start of each run)."""
        self._missing_evidence_requests = []
