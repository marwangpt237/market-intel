"""Unit tests for Phase 9 — Autonomous Research Planner."""
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.models import RawItem, ProcessedItem
from acquisition.knowledge_gap_detector import KnowledgeGapDetector, KnowledgeGap
from acquisition.planner import DataAcquisitionPlanner, CollectionPlan, CollectionAction
from acquisition.engine import AcquisitionEngine


def make_item(title: str, url: str, body: str = "") -> ProcessedItem:
    raw = RawItem.create(source="test", source_name="Test", title=title, url=url, body=body)
    return ProcessedItem.from_raw(raw)


# ─── Knowledge Gap Detector ────────────────────────────────────────────

def test_gap_detector_groups_by_entity_and_type():
    """Multiple missing-evidence requests for same entity+type → one gap."""
    requests = [
        {"claim_id": "c1", "entity": "product:backpack", "claim_type": "average_price", "current_confidence": 0.3, "current_sources": 1, "needed_sources": 2},
        {"claim_id": "c2", "entity": "product:backpack", "claim_type": "average_price", "current_confidence": 0.4, "current_sources": 1, "needed_sources": 2},
        {"claim_id": "c3", "entity": "product:shoes", "claim_type": "demand_level", "current_confidence": 0.2, "current_sources": 1, "needed_sources": 2},
    ]
    detector = KnowledgeGapDetector()
    gaps = detector.detect_gaps(requests)

    # Should group c1+c2 into one gap, c3 into another
    assert len(gaps) == 2
    backpack_gap = next(g for g in gaps if g.entity == "product:backpack")
    assert backpack_gap.affected_claim_count == 2
    assert backpack_gap.current_confidence == 0.35  # avg of 0.3 and 0.4


def test_gap_detector_computes_priority():
    """P0 = high impact + urgent, P3 = minimal."""
    requests = [
        {"claim_id": "c1", "entity": "product:trending", "claim_type": "trend", "current_confidence": 0.1, "current_sources": 1, "needed_sources": 2},
        {"claim_id": "c2", "entity": "product:stable", "claim_type": "best_posting_hours", "current_confidence": 0.85, "current_sources": 1, "needed_sources": 2},
    ]
    detector = KnowledgeGapDetector()
    gaps = detector.detect_gaps(requests)

    # Trend gap should be higher priority (urgent=6h) than best_posting_hours (168h)
    trend_gap = next(g for g in gaps if g.gap_type == "trend")
    hours_gap = next(g for g in gaps if g.gap_type == "best_posting_hours")
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    assert priority_order[trend_gap.priority] <= priority_order[hours_gap.priority]


def test_gap_detector_generates_suggested_queries():
    requests = [
        {"claim_id": "c1", "entity": "product:backpack", "claim_type": "average_price", "current_confidence": 0.3, "current_sources": 1, "needed_sources": 2},
    ]
    detector = KnowledgeGapDetector()
    gaps = detector.detect_gaps(requests)

    gap = gaps[0]
    assert gap.suggested_queries  # non-empty
    # Should contain "backpack" (entity_name derived from entity)
    assert any("backpack" in q for q in gap.suggested_queries)


def test_gap_detector_suggested_source_types():
    """Different claim types → different suggested sources."""
    requests = [
        {"claim_id": "c1", "entity": "product:x", "claim_type": "average_price", "current_confidence": 0.3, "current_sources": 1, "needed_sources": 2},
        {"claim_id": "c2", "entity": "wilaya:Alger", "claim_type": "wilaya_demand", "current_confidence": 0.2, "current_sources": 1, "needed_sources": 2},
    ]
    detector = KnowledgeGapDetector()
    gaps = detector.detect_gaps(requests)

    price_gap = next(g for g in gaps if g.gap_type == "average_price")
    wilaya_gap = next(g for g in gaps if g.gap_type == "wilaya_demand")

    # Price gaps suggest marketplace sources
    assert "ouedkniss" in price_gap.suggested_source_types or "facebook_marketplace" in price_gap.suggested_source_types
    # Wilaya gaps suggest geographic sources
    assert "facebook_groups" in wilaya_gap.suggested_source_types or "ouedkniss" in wilaya_gap.suggested_source_types


def test_gap_detector_handles_empty_requests():
    detector = KnowledgeGapDetector()
    gaps = detector.detect_gaps([])
    assert gaps == []


def test_gap_detector_strips_entity_prefix():
    """product:backpack → entity_name 'backpack' for query templates."""
    requests = [
        {"claim_id": "c1", "entity": "wilaya:Alger", "claim_type": "wilaya_demand", "current_confidence": 0.3, "current_sources": 1, "needed_sources": 2},
    ]
    detector = KnowledgeGapDetector()
    gaps = detector.detect_gaps(requests)

    assert gaps[0].entity_name == "Alger"


# ─── Data Acquisition Planner ──────────────────────────────────────────

def test_planner_generates_plan_for_gap():
    gap = KnowledgeGap(
        gap_id="gap_test1",
        entity="product:backpack",
        entity_name="backpack",
        gap_type="average_price",
        affected_claims=["c1", "c2"],
        affected_claim_count=2,
        current_confidence=0.35,
        target_confidence=0.70,
        confidence_delta=0.35,
        priority="P1",
        suggested_source_types=["ouedkniss", "facebook_marketplace"],
        suggested_queries=["backpack price DZD", "backpack prix DA"],
        collection_urgency_hours=24,
    )
    planner = DataAcquisitionPlanner()
    plans = planner.plan_for_gaps([gap])

    assert len(plans) == 1
    plan = plans[0]
    assert plan.gap_id == "gap_test1"
    assert plan.target_entity == "product:backpack"
    assert len(plan.actions) > 0
    assert plan.estimated_evidence_gain > 0
    assert plan.total_cost > 0


def test_planner_includes_validation_action():
    """Every plan should include a schedule_validation action."""
    gap = KnowledgeGap(
        gap_id="gap_test2",
        entity="product:x",
        entity_name="x",
        gap_type="demand_level",
        affected_claims=["c1"],
        affected_claim_count=1,
        current_confidence=0.3,
        target_confidence=0.70,
        confidence_delta=0.40,
        priority="P1",
        suggested_source_types=["reddit"],
        suggested_queries=["x demand"],
        collection_urgency_hours=12,
    )
    planner = DataAcquisitionPlanner()
    plans = planner.plan_for_gaps([gap])

    plan = plans[0]
    action_types = [a["action_type"] for a in plan.actions]
    assert "schedule_validation" in action_types


def test_planner_includes_crawl_action():
    gap = KnowledgeGap(
        gap_id="gap_test3",
        entity="product:backpack",
        entity_name="backpack",
        gap_type="average_price",
        affected_claims=["c1"],
        affected_claim_count=1,
        current_confidence=0.3,
        target_confidence=0.70,
        confidence_delta=0.40,
        priority="P0",
        suggested_source_types=["ouedkniss"],
        suggested_queries=["backpack price DZD"],
        collection_urgency_hours=24,
    )
    planner = DataAcquisitionPlanner()
    plans = planner.plan_for_gaps([gap])

    plan = plans[0]
    action_types = [a["action_type"] for a in plan.actions]
    assert "crawl" in action_types


def test_planner_includes_historical_for_price_gaps():
    gap = KnowledgeGap(
        gap_id="gap_test4",
        entity="product:phone",
        entity_name="phone",
        gap_type="average_price",
        affected_claims=["c1"],
        affected_claim_count=1,
        current_confidence=0.3,
        target_confidence=0.70,
        confidence_delta=0.40,
        priority="P1",
        suggested_source_types=["ouedkniss"],
        suggested_queries=["phone price"],
        collection_urgency_hours=24,
    )
    planner = DataAcquisitionPlanner()
    plans = planner.plan_for_gaps([gap])

    plan = plans[0]
    action_types = [a["action_type"] for a in plan.actions]
    assert "historical_collection" in action_types


def test_planner_includes_frequency_increase_for_p0():
    gap = KnowledgeGap(
        gap_id="gap_test5",
        entity="product:trending",
        entity_name="trending",
        gap_type="trend",
        affected_claims=["c1"],
        affected_claim_count=1,
        current_confidence=0.2,
        target_confidence=0.70,
        confidence_delta=0.50,
        priority="P0",
        suggested_source_types=["reddit"],
        suggested_queries=["trending"],
        collection_urgency_hours=6,
    )
    planner = DataAcquisitionPlanner()
    plans = planner.plan_for_gaps([gap])

    plan = plans[0]
    action_types = [a["action_type"] for a in plan.actions]
    assert "increase_frequency" in action_types


def test_planner_handles_internal_claim_types():
    """Internal claim types (decision_roi) should still get a minimal plan."""
    gap = KnowledgeGap(
        gap_id="gap_test6",
        entity="decision:hubspot",
        entity_name="hubspot",
        gap_type="decision_roi",
        affected_claims=["c1"],
        affected_claim_count=1,
        current_confidence=0.5,
        target_confidence=0.70,
        confidence_delta=0.20,
        priority="P2",
        suggested_source_types=[],  # internal — no sources
        suggested_queries=[],
        collection_urgency_hours=0,
    )
    planner = DataAcquisitionPlanner()
    plans = planner.plan_for_gaps([gap])

    # Should still produce a plan with just schedule_validation
    assert len(plans) == 1
    plan = plans[0]
    action_types = [a["action_type"] for a in plan.actions]
    assert "schedule_validation" in action_types


def test_planner_caps_actions_per_plan():
    gap = KnowledgeGap(
        gap_id="gap_test7",
        entity="product:x",
        entity_name="x",
        gap_type="average_price",
        affected_claims=["c1"],
        affected_claim_count=1,
        current_confidence=0.3,
        target_confidence=0.70,
        confidence_delta=0.40,
        priority="P0",
        suggested_source_types=["ouedkniss", "facebook_marketplace", "rss"],
        suggested_queries=["x price", "x prix", "x ثمن"],
        collection_urgency_hours=24,
    )
    planner = DataAcquisitionPlanner({"max_actions_per_plan": 3})
    plans = planner.plan_for_gaps([gap])

    plan = plans[0]
    assert len(plan.actions) <= 3


def test_planner_caps_plans_per_run():
    """Should cap total plans per run."""
    gaps = []
    for i in range(30):
        gaps.append(KnowledgeGap(
            gap_id=f"gap_{i}",
            entity=f"product:x{i}",
            entity_name=f"x{i}",
            gap_type="average_price",
            affected_claims=[f"c{i}"],
            affected_claim_count=1,
            current_confidence=0.3,
            target_confidence=0.70,
            confidence_delta=0.40,
            priority="P2",
            suggested_source_types=["rss"],
            suggested_queries=[f"x{i}"],
            collection_urgency_hours=24,
        ))
    planner = DataAcquisitionPlanner({"max_plans_per_run": 10})
    plans = planner.plan_for_gaps(gaps)

    assert len(plans) <= 10


def test_planner_computes_estimated_evidence_and_cost():
    gap = KnowledgeGap(
        gap_id="gap_test8",
        entity="product:backpack",
        entity_name="backpack",
        gap_type="average_price",
        affected_claims=["c1"],
        affected_claim_count=1,
        current_confidence=0.3,
        target_confidence=0.70,
        confidence_delta=0.40,
        priority="P1",
        suggested_source_types=["ouedkniss"],
        suggested_queries=["backpack price"],
        collection_urgency_hours=24,
    )
    planner = DataAcquisitionPlanner()
    plans = planner.plan_for_gaps([gap])

    plan = plans[0]
    assert plan.estimated_evidence_gain > 0
    assert plan.total_cost > 0
    assert plan.estimated_confidence_lift > 0


# ─── Acquisition Engine (integration) ──────────────────────────────────

def test_acquisition_engine_end_to_end():
    """Full pipeline: validation output → gap detection → plan generation."""
    tmpdir = tempfile.mkdtemp()
    try:
        engine = AcquisitionEngine({})

        items = [make_item("Test", "http://1.com")]
        # Simulate validation output with missing-evidence requests
        items[0].metadata["_validation"] = {
            "missing_evidence_requests": [
                {"claim_id": "c1", "entity": "product:backpack", "claim_type": "average_price",
                 "current_confidence": 0.3, "current_sources": 1, "needed_sources": 2},
                {"claim_id": "c2", "entity": "product:backpack", "claim_type": "average_price",
                 "current_confidence": 0.4, "current_sources": 1, "needed_sources": 2},
                {"claim_id": "c3", "entity": "wilaya:Alger", "claim_type": "wilaya_demand",
                 "current_confidence": 0.2, "current_sources": 1, "needed_sources": 2},
            ],
        }

        result = engine.process(items)

        assert "_acquisition" in result[0].metadata
        acq = result[0].metadata["_acquisition"]

        # Should detect 2 gaps (backpack price + wilaya Alger)
        assert acq["summary"]["total_gaps"] == 2
        # Should generate 2 plans
        assert acq["summary"]["total_plans"] == 2
        # Should have estimated evidence
        assert acq["summary"]["total_estimated_evidence"] > 0
        # Should have a next_validation_hours
        assert acq["summary"]["next_validation_hours"] > 0

        # Plans should have actions
        for plan in acq["plans"]:
            assert len(plan["actions"]) > 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_acquisition_engine_handles_no_missing_evidence():
    """When validation finds no gaps, acquisition should produce empty output."""
    engine = AcquisitionEngine({})
    items = [make_item("Test", "http://1.com")]
    items[0].metadata["_validation"] = {
        "missing_evidence_requests": [],
    }

    result = engine.process(items)
    acq = result[0].metadata["_acquisition"]
    assert acq["summary"]["total_gaps"] == 0
    assert acq["summary"]["total_plans"] == 0


def test_acquisition_engine_handles_no_validation_data():
    """When no validation ran, acquisition should skip gracefully."""
    engine = AcquisitionEngine({})
    items = [make_item("Test", "http://1.com")]
    # No _validation metadata

    result = engine.process(items)
    # Should not crash, should not add _acquisition metadata
    assert "_acquisition" not in result[0].metadata


def test_acquisition_engine_prioritizes_p0_gaps():
    """P0 gaps should appear first in the plans list."""
    engine = AcquisitionEngine({})
    items = [make_item("Test", "http://1.com")]
    items[0].metadata["_validation"] = {
        "missing_evidence_requests": [
            # P3 gap (low urgency)
            {"claim_id": "c1", "entity": "product:stable", "claim_type": "best_posting_hours",
             "current_confidence": 0.85, "current_sources": 1, "needed_sources": 2},
            # P0 gap (trend, urgent)
            {"claim_id": "c2", "entity": "product:trending", "claim_type": "trend",
             "current_confidence": 0.1, "current_sources": 1, "needed_sources": 2},
        ],
    }

    result = engine.process(items)
    acq = result[0].metadata["_acquisition"]

    # First plan should be the trend gap (higher priority)
    first_plan = acq["plans"][0]
    assert first_plan["priority"] in ("P0", "P1")
    assert first_plan["gap_type"] == "trend"
