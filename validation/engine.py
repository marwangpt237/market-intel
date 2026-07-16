"""
Validation Engine — Phase 8 core subsystem orchestrator.

This is the main entry point for the Evidence Validation Engine.
It runs as a processor in the pipeline (after all other processors
have produced their outputs) and:

  1. Extracts claims from all items via ClaimExtractor
  2. Validates each claim via EvidenceValidator
  3. Records decisions in the DecisionLedger with claim references
  4. Stashes validation summary on items[0] for the Validation Report

No fact, metric, recommendation, score, trend, or confidence value
should enter the knowledge base unless it has been evaluated by this engine.
"""
from __future__ import annotations

from datetime import datetime, timezone
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor
from validation.trust_layer import TrustLayer
from validation.claim_store import ClaimStore
from validation.claim_extractor import ClaimExtractor
from validation.evidence_validator import EvidenceValidator
from validation.decision_ledger import DecisionLedger, compute_decision_confidence


class ValidationEngine(BaseProcessor):
    """Phase 8 — Evidence Validation Engine.

    Runs as a processor in the pipeline. Extracts claims from all items,
    validates them, records decisions in the ledger.

    Configuration (under processors.validation_engine in config):
      enabled: true
      min_sources_probable: 2
      min_sources_verified: 3
      min_evidence_reliability: 0.30
      contradiction_tolerance: 0.30
    """
    name = "validation_engine"

    def __init__(self, config: dict | None = None):
        super().__init__(config)

        # Storage config — same DB as the rest of the platform
        storage_cfg = self._config.get("storage", {})
        self._db_path = storage_cfg.get("path", "data/market_intel.db")

        # Initialize subsystems
        self._trust_layer = TrustLayer(self._config.get("trust_layer", {}))
        self._claim_store = ClaimStore(self._db_path)
        self._extractor = ClaimExtractor(self._trust_layer, self._config.get("claim_extractor", {}))
        self._validator = EvidenceValidator(
            self._claim_store,
            self._trust_layer,
            self._config.get("validator", {}),
        )
        self._ledger = DecisionLedger(self._db_path)

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        if not items:
            return items

        # Clear missing-evidence requests from previous run
        self._validator.clear_missing_evidence_requests()

        # 1. Extract claims + evidence from items
        claims_with_evidence = self._extractor.extract_from_items(items)
        self._logger.info(f"Extracted {len(claims_with_evidence)} claims from {len(items)} items")

        # 2. Group evidence by claim_id (multiple items may contribute to same claim)
        grouped: dict[str, tuple] = {}  # claim_id → (Claim, [Evidence])
        for claim, evidence in claims_with_evidence:
            if claim.id in grouped:
                # Merge evidence into existing claim
                existing_claim, existing_evidence = grouped[claim.id]
                existing_evidence.extend(evidence)
                # Update last_seen to latest
                grouped[claim.id] = (existing_claim, existing_evidence)
            else:
                grouped[claim.id] = (claim, list(evidence))

        # 3. Validate each claim
        validated_claims = []
        for claim_id, (claim, evidence) in grouped.items():
            validated = self._validator.validate_claim(claim, evidence)
            validated_claims.append(validated)

        # 4. Check for stale claims (claims from previous runs not seen this run)
        stale_claims = self._mark_stale_claims({c.id for c in validated_claims})

        # 5. Record decisions in the ledger (with claim references)
        decisions_recorded = self._record_decisions_in_ledger(items)

        # 6. Build summary
        missing_evidence = self._validator.get_missing_evidence_requests()
        store_stats = self._claim_store.get_stats()
        ledger_stats = self._ledger.get_stats()
        trust_stats = self._trust_layer.get_stats()

        summary = {
            "claims_extracted": len(claims_with_evidence),
            "unique_claims": len(grouped),
            "claims_validated": len(validated_claims),
            "stale_claims_marked": len(stale_claims),
            "decisions_recorded": decisions_recorded,
            "missing_evidence_requests": missing_evidence,
            "store_stats": store_stats,
            "ledger_stats": ledger_stats,
            "trust_stats": trust_stats,
            "newly_verified": [c for c in validated_claims if c.validation_status == "VERIFIED"],
            "newly_probable": [c for c in validated_claims if c.validation_status == "PROBABLE"],
            "newly_hypothesis": [c for c in validated_claims if c.validation_status == "HYPOTHESIS"],
            "conflicted_claims": [c for c in validated_claims if c.validation_status == "CONFLICTED"],
            "expired_claims": stale_claims,
            "highest_confidence_claims": sorted(validated_claims, key=lambda c: -c.confidence_score)[:5],
            "lowest_confidence_claims": sorted([c for c in validated_claims if c.confidence_score > 0], key=lambda c: c.confidence_score)[:5],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Convert claim objects to dicts for serialization
        for key in ("newly_verified", "newly_probable", "newly_hypothesis",
                    "conflicted_claims", "expired_claims",
                    "highest_confidence_claims", "lowest_confidence_claims"):
            summary[key] = [c.to_dict() if hasattr(c, "to_dict") else c for c in summary[key]]

        items[0].metadata["_validation"] = summary

        self._logger.info(
            f"Validation engine: {len(validated_claims)} claims validated, "
            f"{len(stale_claims)} stale, {decisions_recorded} decisions recorded, "
            f"{len(missing_evidence)} missing-evidence requests"
        )
        return items

    def _mark_stale_claims(self, current_claim_ids: set[str]) -> list[dict]:
        """Mark claims not seen this run as stale (EXPIRED).

        Returns list of expired claim dicts.
        """
        # Get all claims from store
        all_claims = self._claim_store.get_all_claims(limit=5000)
        expired: list[dict] = []

        for claim in all_claims:
            if claim.id not in current_claim_ids and claim.validation_status != "EXPIRED":
                # Check if it's actually past expiration date
                if self._validator._is_stale(claim):
                    old_status = claim.validation_status
                    old_confidence = claim.confidence_score
                    claim.validation_status = "EXPIRED"
                    self._claim_store.upsert_claim(claim)
                    self._claim_store.add_version_history(
                        claim_id=claim.id,
                        old_status=old_status,
                        new_status="EXPIRED",
                        old_confidence=old_confidence,
                        new_confidence=old_confidence,
                        reason="Claim not seen this run + past expiration date",
                    )
                    expired.append(claim.to_dict())

        return expired

    def _record_decisions_in_ledger(self, items: list[ProcessedItem]) -> int:
        """Record each decision in the ledger with claim references.

        For each decision (from Decision Engine / Strategy Engine output),
        find the claims that justify it and record the linkage.
        """
        if not items:
            return 0

        recorded = 0
        first_item = items[0]

        # Find decisions
        decisions_data = first_item.metadata.get("_decisions", {})
        decisions = decisions_data.get("decisions", []) if isinstance(decisions_data, dict) else []

        # Find strategy-selected decisions
        strategy_data = first_item.metadata.get("_strategy", {})
        selected = strategy_data.get("selected", []) if isinstance(strategy_data, dict) else []

        # Record each selected decision in the ledger
        for selected_item in selected:
            decision = selected_item.get("decision", {})
            target = decision.get("target", "unknown")
            target_lower = target.lower() if target else "unknown"

            # Find claims that justify this decision
            # Look for claims whose entity matches the decision target
            related_claims: list[dict] = []
            for claim in self._claim_store.get_all_claims(limit=1000):
                if target_lower in claim.entity.lower() or claim.entity.lower() in target_lower:
                    related_claims.append({
                        "claim_id": claim.id,
                        "confidence": claim.confidence_score,
                        "status": claim.validation_status,
                        "claim_type": claim.claim_type,
                        "entity": claim.entity,
                        "value": claim.value,
                    })

            # Compute decision confidence from claim confidences
            decision_confidence, warnings = compute_decision_confidence(related_claims)

            # Add warning if no claims found
            if not related_claims:
                warnings.append(f"No validated claims found for target '{target}' — decision is unsupported")

            # Record in ledger
            self._ledger.record_decision(
                decision_id=decision.get("id", ""),
                decision_type=decision.get("type", ""),
                target=target,
                priority=decision.get("priority", ""),
                suggested_action=decision.get("suggested_action", ""),
                claim_ids=[c["claim_id"] for c in related_claims],
                claim_confidences=related_claims,
                decision_confidence=decision_confidence,
                warnings=warnings,
            )
            recorded += 1

        return recorded
