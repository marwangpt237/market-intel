"""
Acquisition Engine — Phase 9 orchestrator.

Runs as a processor in the pipeline (after Validation Engine).
Reads missing-evidence requests from the Validation Engine's output,
detects knowledge gaps, generates collection plans, and stashes
the results for the Acquisition Report.

This is the autonomous research planner. Instead of passively reporting
missing evidence, it actively plans how to obtain it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor
from acquisition.knowledge_gap_detector import KnowledgeGapDetector
from acquisition.planner import DataAcquisitionPlanner


class AcquisitionEngine(BaseProcessor):
    """Phase 9 — Autonomous Research Planner.

    Pipeline:
      1. Read missing-evidence requests from Validation Engine output
      2. Detect knowledge gaps (group by entity + claim_type)
      3. Generate collection plans (concrete actions per gap)
      4. Stash summary on items[0] for Acquisition Report

    Configuration (under processors.acquisition_engine in config):
      enabled: true
      max_plans_per_run: 20
      max_actions_per_plan: 5
    """
    name = "acquisition_engine"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._gap_detector = KnowledgeGapDetector(self._config.get("gap_detector", {}))
        self._planner = DataAcquisitionPlanner(self._config.get("planner", {}))

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        if not items:
            return items

        # Find validation output
        validation_data = None
        for item in items:
            if "_validation" in item.metadata:
                validation_data = item.metadata["_validation"]
                break

        if not validation_data:
            self._logger.info("No validation data — skipping acquisition engine")
            return items

        missing_evidence = validation_data.get("missing_evidence_requests", [])
        if not missing_evidence:
            self._logger.info("No missing-evidence requests — knowledge base is complete")
            items[0].metadata["_acquisition"] = {
                "gaps": [],
                "plans": [],
                "summary": {
                    "total_gaps": 0,
                    "total_plans": 0,
                    "total_estimated_evidence": 0,
                    "total_confidence_lift": 0.0,
                    "total_cost": 0.0,
                    "next_validation_hours": 24,
                },
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            return items

        # 1. Detect knowledge gaps
        gaps = self._gap_detector.detect_gaps(missing_evidence)

        # 2. Generate collection plans
        plans = self._planner.plan_for_gaps(gaps)

        # 3. Build summary
        total_evidence = sum(p.estimated_evidence_gain for p in plans)
        total_lift = sum(p.estimated_confidence_lift for p in plans)
        total_cost = sum(p.total_cost for p in plans)
        next_validation = min((p.next_validation_hours for p in plans), default=24)

        summary = {
            "total_gaps": len(gaps),
            "total_plans": len(plans),
            "total_estimated_evidence": total_evidence,
            "total_confidence_lift": round(total_lift, 3),
            "total_cost": round(total_cost, 2),
            "next_validation_hours": next_validation,
            "gaps_by_priority": {
                "P0": sum(1 for g in gaps if g.priority == "P0"),
                "P1": sum(1 for g in gaps if g.priority == "P1"),
                "P2": sum(1 for g in gaps if g.priority == "P2"),
                "P3": sum(1 for g in gaps if g.priority == "P3"),
            },
        }

        items[0].metadata["_acquisition"] = {
            "gaps": [g.to_dict() for g in gaps],
            "plans": [p.to_dict() for p in plans],
            "summary": summary,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        self._logger.info(
            f"Acquisition engine: {len(gaps)} gaps detected, {len(plans)} plans generated, "
            f"est. {total_evidence} evidence pieces, +{total_lift:.2f} confidence lift, "
            f"cost {total_cost:.1f}, next validation in {next_validation}h"
        )
        return items
