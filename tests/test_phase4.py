"""Unit tests for Phase 4 modules: Decision / Execution / Analytics / Learning."""
import sys
import os
import json
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.models import RawItem, ProcessedItem
from processors.decision_engine import DecisionEngine
from processors.execution_engine import ExecutionEngine
from processors.analytics_engine import AnalyticsEngine
from processors.learning_engine import LearningEngine


def make_item(title: str, url: str, body: str = "") -> ProcessedItem:
    raw = RawItem.create(source="test", source_name="Test", title=title, url=url, body=body)
    return ProcessedItem.from_raw(raw)


# ─── Decision Engine ────────────────────────────────────────────────────

def test_decision_engine_generates_decisions_from_scores():
    items = [make_item("HubSpot too expensive, looking for alternative", "http://1.com")]
    items[0].metadata["entities"] = {"companies": ["hubspot"], "products": [], "people": []}
    items[0].metadata["pain_points"] = [{"category": "pricing", "severity": "high", "text": "expensive"}]
    items[0].metadata["buying_signals"] = [{"type": "evaluation", "confidence": 0.7, "text": "alternative"}]
    items[0].metadata["competitor_mentions"] = [{"competitor": "hubspot", "signal": "seeking_alternative", "category": "Marketing"}]
    items[0].metadata["_scores"] = {
        "company_scores": [
            {
                "entity": "hubspot",
                "type": "company",
                "opportunity_score": 75,      # above opportunity_high=60
                "threat_score": 30,
                "competitor_weakness_score": 60,  # above weakness_high=50
                "data": {
                    "mentions": 5,
                    "pain_points": 3,
                    "buying_signals": 2,
                    "pricing_complaints": 4,
                    "seeking_alternatives": 3,
                    "positive_sentiment": 0,
                    "negative_sentiment": 5,
                },
            }
        ],
        "topic_scores": [],
        "insights": [],
    }

    engine = DecisionEngine({"opportunity_high": 60, "weakness_high": 50})
    result = engine.process(items)

    decisions_data = result[0].metadata.get("_decisions", {})
    decisions = decisions_data.get("decisions", [])
    assert len(decisions) > 0
    # Should have a P0 build_feature decision for hubspot
    build_decisions = [d for d in decisions if d["type"] == "build_feature" and d["target"] == "hubspot"]
    assert len(build_decisions) >= 1
    assert build_decisions[0]["priority"] == "P0"
    assert "hubspot" in build_decisions[0]["rationale"].lower()
    # Should have at least one decision with evidence
    assert any(d.get("evidence") for d in decisions)


def test_decision_engine_topics_create_write_content_decisions():
    items = [make_item("AI SEO tools rising fast", "http://1.com")]
    items[0].metadata["cluster_label"] = "ai-seo-tools"
    items[0].metadata["trend"] = "hot"
    items[0].metadata["_scores"] = {
        "company_scores": [],
        "topic_scores": [
            {
                "entity": "ai-seo-tools",
                "type": "topic",
                "trend_score": 80,
                "opportunity_score": 50,
                "data": {"mentions": 12, "pain_points": 4, "buying_signals": 6, "trend": "hot"},
            }
        ],
        "insights": [],
    }

    engine = DecisionEngine({"trend_hot": 60})
    result = engine.process(items)

    decisions = result[0].metadata["_decisions"]["decisions"]
    write_decisions = [d for d in decisions if d["type"] == "write_content"]
    assert len(write_decisions) >= 1
    assert write_decisions[0]["target"] == "ai-seo-tools"
    assert write_decisions[0]["urgency_hours"] == 168


def test_decision_engine_dedups_by_id():
    items = [make_item("test", "http://1.com")]
    items[0].metadata["_scores"] = {
        "company_scores": [
            {"entity": "x", "opportunity_score": 80, "threat_score": 70, "competitor_weakness_score": 70, "data": {"buying_signals": 0}},
        ],
        "topic_scores": [],
        "insights": [],
    }
    engine = DecisionEngine({"opportunity_high": 60, "weakness_high": 50, "threat_high": 60})
    result = engine.process(items)
    decisions = result[0].metadata["_decisions"]["decisions"]
    # Same target + same type → same ID → deduped
    ids = [d["id"] for d in decisions]
    assert len(ids) == len(set(ids)), "Duplicate decision IDs found"


# ─── Execution Engine ───────────────────────────────────────────────────

def test_execution_engine_generates_artifacts():
    tmpdir = tempfile.mkdtemp()
    try:
        items = [make_item("test", "http://1.com")]
        items[0].metadata["_decisions"] = {
            "decisions": [
                {
                    "id": "dec_abc123",
                    "type": "build_feature",
                    "priority": "P0",
                    "target": "hubspot",
                    "rationale": "Opportunity score 75, weakness 60",
                    "expected_impact": "high",
                    "suggested_action": "Build alternative",
                    "evidence": [{"item_id": "1", "title": "HubSpot too expensive", "url": "http://1.com", "source": "Reddit"}],
                    "created_at": "2026-07-15T00:00:00+00:00",
                },
                {
                    "id": "dec_def456",
                    "type": "write_content",
                    "priority": "P1",
                    "target": "ai-seo",
                    "rationale": "Trending hot",
                    "expected_impact": "medium",
                    "suggested_action": "Publish blog post",
                    "evidence": [],
                    "urgency_hours": 168,
                    "created_at": "2026-07-15T00:00:00+00:00",
                },
            ],
            "total": 2,
            "by_priority": {"P0": 1, "P1": 1, "P2": 0, "P3": 0},
            "by_type": {"build_feature": 1, "write_content": 1},
        }

        engine = ExecutionEngine({"output_path": tmpdir, "max_artifacts_per_run": 10})
        result = engine.process(items)

        executions = result[0].metadata["_executions"]
        assert executions["total"] == 2
        assert len(executions["artifacts"]) == 2
        # Each artifact should have content + path
        for artifact in executions["artifacts"]:
            assert artifact["content"]
            assert os.path.exists(artifact["path"])
            # Verify file content is non-empty markdown
            with open(artifact["path"], "r") as f:
                content = f.read()
            assert content.startswith("#")
            assert len(content) > 200  # substantive content

        # Verify specific artifact types
        types = [a["type"] for a in executions["artifacts"]]
        assert "build_feature" in types
        assert "write_content" in types
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_execution_engine_skips_when_no_decisions():
    items = [make_item("test", "http://1.com")]
    engine = ExecutionEngine({"output_path": tempfile.mkdtemp()})
    result = engine.process(items)
    assert "_executions" not in result[0].metadata


# ─── Analytics Engine ───────────────────────────────────────────────────

def test_analytics_engine_records_actions():
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        items = [make_item("test", "http://1.com")]
        items[0].metadata["_executions"] = {
            "artifacts": [
                {
                    "decision_id": "dec_abc123",
                    "type": "build_feature",
                    "path": "/tmp/some_artifact.md",
                    "content": "# test",
                }
            ],
            "total": 1,
            "output_dir": "/tmp",
        }
        items[0].metadata["_decisions"] = {
            "decisions": [
                {"id": "dec_abc123", "target": "hubspot", "priority": "P0", "expected_impact": "high"}
            ],
        }

        engine = AnalyticsEngine({"storage": {"path": db_path}})
        result = engine.process(items)

        analytics = result[0].metadata["_analytics"]
        assert analytics["actions_recorded_this_run"] == 1
        assert analytics["total_actions_in_db"] == 1
        assert "dec_abc123" in analytics["new_action_ids"]
        # metrics template should exist
        assert os.path.exists(analytics["metrics_input_path"])

        # Run again — should not double-insert
        items2 = [make_item("test2", "http://2.com")]
        items2[0].metadata["_executions"] = items[0].metadata["_executions"]
        items2[0].metadata["_decisions"] = items[0].metadata["_decisions"]
        engine.process(items2)
        # Re-load summary
        import sqlite3
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
        conn.close()
        assert count == 1, f"Expected 1 action, got {count}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ─── Learning Engine ────────────────────────────────────────────────────

def test_learning_engine_syncs_metrics_from_template():
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        # Seed an action via analytics engine
        items = [make_item("test", "http://1.com")]
        items[0].metadata["_executions"] = {
            "artifacts": [{"decision_id": "dec_abc123", "type": "build_feature", "path": "/tmp/x.md", "content": "# x"}],
            "total": 1,
        }
        items[0].metadata["_decisions"] = {"decisions": [{"id": "dec_abc123", "target": "hubspot", "priority": "P0", "expected_impact": "high"}]}

        analytics = AnalyticsEngine({"storage": {"path": db_path}})
        analytics.process(items)

        # User fills in metrics template
        template_path = os.path.join(os.path.dirname(db_path), "metrics_input_template.json")
        with open(template_path, "r") as f:
            template = json.load(f)
        for action in template["actions"]:
            action["clicks"] = 100
            action["signups"] = 5
            action["conversions"] = 1
            action["revenue"] = 99.0
            action["status"] = "published"
        with open(template_path, "w") as f:
            json.dump(template, f)

        # Run learning engine — should sync metrics + persist weights
        learning = LearningEngine({"storage": {"path": db_path}})
        result = learning.process(items)

        learning_data = result[0].metadata["_learning"]
        assert learning_data["metrics_synced"] == 1
        assert "current_weights" in learning_data
        assert "new_weights" in learning_data

        # Weights file should exist
        weights_path = os.path.join(os.path.dirname(db_path), "learning_weights.json")
        assert os.path.exists(weights_path)
        with open(weights_path, "r") as f:
            weights = json.load(f)
        assert "opportunity_high" in weights
        assert "last_updated" in weights
        assert "data_points" in weights
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_learning_engine_runs_with_empty_db():
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        items = [make_item("test", "http://1.com")]
        engine = LearningEngine({"storage": {"path": db_path}})
        result = engine.process(items)
        # Should not crash, should produce empty adjustments
        learning = result[0].metadata["_learning"]
        assert learning["weight_adjustments"] == []
        assert learning["data_points"] == 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ─── End-to-end: Score → Decide → Execute → Analytics ───────────────────

def test_phase4_end_to_end_pipeline():
    """Full Phase 4 pipeline: scores → decisions → executions → analytics."""
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")

        # Stage 1: scores already on item (simulating scoring engine output)
        items = [make_item("HubSpot pricing complaints", "http://1.com", body="Looking for cheaper option")]
        items[0].metadata["entities"] = {"companies": ["hubspot"], "products": [], "people": []}
        items[0].metadata["pain_points"] = [{"category": "pricing", "severity": "high", "text": "expensive"}]
        items[0].metadata["buying_signals"] = [{"type": "budget", "confidence": 0.8, "text": "cheaper"}]
        items[0].metadata["competitor_mentions"] = [{"competitor": "hubspot", "signal": "pricing_complaint", "category": "Marketing"}]
        items[0].metadata["_scores"] = {
            "company_scores": [{
                "entity": "hubspot",
                "type": "company",
                "opportunity_score": 80,
                "threat_score": 50,
                "competitor_weakness_score": 65,
                "data": {
                    "mentions": 5, "pain_points": 3, "buying_signals": 2,
                    "pricing_complaints": 4, "seeking_alternatives": 3,
                    "positive_sentiment": 0, "negative_sentiment": 5,
                },
            }],
            "topic_scores": [],
            "insights": [],
        }

        # Stage 2: Decision engine
        decisions = DecisionEngine({"opportunity_high": 60, "weakness_high": 50})
        items = decisions.process(items)
        assert items[0].metadata["_decisions"]["total"] > 0

        # Stage 3: Execution engine
        executions = ExecutionEngine({"output_path": os.path.join(tmpdir, "actions")})
        items = executions.process(items)
        assert items[0].metadata["_executions"]["total"] > 0

        # Stage 4: Analytics engine
        analytics = AnalyticsEngine({"storage": {"path": db_path}})
        items = analytics.process(items)
        assert items[0].metadata["_analytics"]["total_actions_in_db"] > 0

        # Stage 5: Learning engine
        learning = LearningEngine({"storage": {"path": db_path}})
        items = learning.process(items)
        assert "_learning" in items[0].metadata

        # Verify the closed loop completed
        assert items[0].metadata["_decisions"]["total"] > 0
        assert items[0].metadata["_executions"]["total"] > 0
        assert items[0].metadata["_analytics"]["actions_recorded_this_run"] > 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
