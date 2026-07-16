"""Unit tests for Phase 6 — LearnedScorer + FeatureExtractor + FeatureWeightsStore."""
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.models import RawItem, ProcessedItem
from processors.feature_extractor import FeatureExtractor, FeatureVector, BASELINE_WEIGHTS, BASELINE_BIAS
from processors.learned_scorer import LearnedScorer
from storage.feature_weights_store import FeatureWeightsStore


def make_item(title: str, url: str, body: str = "", source: str = "test", source_name: str = "Test") -> ProcessedItem:
    raw = RawItem.create(source=source, source_name=source_name, title=title, url=url, body=body)
    return ProcessedItem.from_raw(raw)


# ─── Feature Extractor ─────────────────────────────────────────────────

def test_feature_extractor_extracts_counting_features():
    item1 = make_item("HubSpot pricing insane", "http://1.com", body="Need cheaper alternative")
    item1.metadata["pain_points"] = [{"category": "pricing", "severity": "high", "text": "expensive"}]
    item1.metadata["buying_signals"] = [{"type": "budget", "confidence": 0.8, "text": "cheaper"}]
    item1.metadata["competitor_mentions"] = [{"competitor": "hubspot", "signal": "pricing_complaint", "category": "Marketing"}]
    item1.metadata["sentiment"] = "negative"
    item1.metadata["authority_score"] = 85

    decision = {
        "type": "build_feature",
        "priority": "P0",
        "target": "hubspot",
        "expected_impact": "high",
        "evidence": [{"item_id": item1.id, "title": "t", "url": "u", "source": "HN"}],
    }

    extractor = FeatureExtractor()
    fv = extractor.extract(decision, [item1])

    assert fv.features["pain_point_count"] == 1.0
    assert fv.features["buying_signal_count"] == 1.0
    assert fv.features["pricing_complaint_count"] == 1.0
    assert fv.features["negative_sentiment_count"] == 1.0
    assert fv.features["evidence_count"] == 1.0
    assert fv.features["avg_authority_score"] == 85.0
    assert fv.features["type_build_feature"] == 1.0
    assert fv.features["priority_P0"] == 1.0
    assert fv.features["impact_high"] == 1.0


def test_feature_extractor_extracts_domain_signals():
    item = make_item("Critical CVE-2024-12345 RCE", "http://1.com", body="Patch now, actively exploited")
    item.metadata["domain_signals"] = {
        "cybersecurity": {"signals": ["cve_mention"], "severity": "high", "severity_score": 3}
    }
    item.metadata["authority_score"] = 90

    decision = {
        "type": "monitor_competitor",
        "priority": "P1",
        "target": "apache",
        "expected_impact": "low",
        "evidence": [{"item_id": item.id, "title": "t", "url": "u", "source": "HN"}],
    }

    extractor = FeatureExtractor()
    fv = extractor.extract(decision, [item])

    assert fv.features["cybersecurity_high_severity_count"] == 1.0
    assert fv.features["avg_severity_score"] == 3.0
    assert fv.features["type_monitor_competitor"] == 1.0


def test_feature_extractor_one_hot_features():
    item = make_item("test", "http://1.com")
    decision = {
        "type": "write_content",
        "priority": "P2",
        "target": "ai-seo",
        "expected_impact": "medium",
        "urgency_hours": 168,
        "evidence": [],
    }

    extractor = FeatureExtractor()
    fv = extractor.extract(decision, [item])

    assert fv.features["type_write_content"] == 1.0
    assert fv.features["priority_P2"] == 1.0
    assert fv.features["impact_medium"] == 1.0
    assert fv.features["has_urgency"] == 1.0
    # Other type one-hots should not be present
    assert "type_build_feature" not in fv.features
    assert "priority_P0" not in fv.features


def test_feature_extractor_pulls_scores_from_items():
    item = make_item("test", "http://1.com")
    item.metadata["_scores"] = {
        "company_scores": [{
            "entity": "hubspot",
            "opportunity_score": 80,
            "threat_score": 40,
            "competitor_weakness_score": 70,
        }],
        "topic_scores": [],
        "insights": [],
    }

    decision = {
        "type": "launch_campaign",
        "priority": "P1",
        "target": "hubspot",
        "expected_impact": "high",
        "evidence": [],
    }

    extractor = FeatureExtractor()
    fv = extractor.extract(decision, [item])

    assert fv.features["opportunity_score"] == 80.0
    assert fv.features["threat_score"] == 40.0
    assert fv.features["competitor_weakness"] == 70.0


def test_baseline_weights_reasonable():
    """Baseline weights should produce a score in 0-300 range for typical features
    (will be clamped to 0-100 at predict time)."""
    # Build a feature vector for a typical P0 build_feature decision
    fv = FeatureVector()
    fv.set("pain_point_count", 3.0)
    fv.set("buying_signal_count", 2.0)
    fv.set("seeking_alternative_count", 2.0)
    fv.set("evidence_count", 5.0)
    fv.set("source_diversity", 3.0)
    fv.set("avg_authority_score", 75.0)
    fv.set("opportunity_score", 80.0)
    fv.set("type_build_feature", 1.0)
    fv.set("priority_P0", 1.0)
    fv.set("impact_high", 1.0)

    # Compute score using baseline weights
    score = BASELINE_BIAS
    for name, value in fv.features.items():
        score += value * BASELINE_WEIGHTS.get(name, 0.0)

    # Should be in a reasonable range (will clamp at predict time)
    assert score > 30, f"Baseline score too low: {score}"
    # When clamped, will be 100 — that's expected for high-impact decisions
    clamped = max(0.0, min(100.0, score))
    assert clamped == 100.0, f"High-impact decision should clamp at 100, got {clamped}"


# ─── Feature Weights Store ─────────────────────────────────────────────

def test_feature_weights_store_persists_and_loads():
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        store = FeatureWeightsStore(db_path)

        # Upsert a weight
        store.upsert("pain_point_count", weight=18.5, baseline_weight=15.0, samples=10, total_gradient=2.5)

        # Load it back
        record = store.get_weight("pain_point_count")
        assert record is not None
        assert record["weight"] == 18.5
        assert record["baseline_weight"] == 15.0
        assert record["samples"] == 10

        # Load all
        all_weights = store.load_all()
        assert "pain_point_count" in all_weights

        # Stats
        stats = store.get_stats()
        assert stats["total_features"] == 1
        assert stats["features_with_enough_samples"] == 1
        assert stats["total_samples"] == 10
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_feature_weights_store_increment_and_update():
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        store = FeatureWeightsStore(db_path)

        # First insert (samples=1)
        store.increment_and_update("buying_signal_count", new_weight=22.0, baseline_weight=20.0, gradient_abs=0.5)
        record = store.get_weight("buying_signal_count")
        assert record["samples"] == 1
        assert record["weight"] == 22.0
        assert record["total_gradient"] == 0.5

        # Second increment (samples=2)
        store.increment_and_update("buying_signal_count", new_weight=23.5, baseline_weight=20.0, gradient_abs=0.3)
        record = store.get_weight("buying_signal_count")
        assert record["samples"] == 2
        assert record["weight"] == 23.5
        assert record["total_gradient"] == 0.8  # 0.5 + 0.3
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ─── Learned Scorer ────────────────────────────────────────────────────

def test_learned_scorer_predict_uses_baseline_on_cold_start():
    """With 0 samples, predict() should use baseline weights."""
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        scorer = LearnedScorer(db_path)
        scorer.load()  # empty store

        fv = FeatureVector()
        fv.set("pain_point_count", 2.0)
        fv.set("buying_signal_count", 1.0)
        fv.set("type_build_feature", 1.0)
        fv.set("priority_P0", 1.0)

        prediction = scorer.predict(fv)
        # Should be in 0-100 range (clamped)
        assert 0 <= prediction <= 100

        # Should be > bias alone (since all features are positive)
        assert prediction > BASELINE_BIAS

        stats = scorer.get_stats()
        assert stats["features_with_enough_samples"] == 0  # all cold-start
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_learned_scorer_update_changes_weights():
    """After update() with a low outcome, weights should decrease.

    Uses small feature values so predictions don't clamp at 100.
    """
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        scorer = LearnedScorer(db_path, learning_rate=0.1)  # large LR for visible effect
        scorer.load()

        # Use small feature values to avoid clamping at 100
        fv = FeatureVector()
        fv.set("pain_point_count", 1.0)  # small value
        fv.set("priority_P2", 1.0)       # lower-priority (less weight)
        fv.set("impact_low", 1.0)        # lower impact

        # Predict before
        pred_before = scorer.predict(fv)
        assert pred_before < 100, f"Test setup issue: prediction should not be at clamp, got {pred_before}"

        # Update with a very low outcome (model predicted higher than actual)
        error = scorer.update(fv, actual_outcome=2.0)

        # Prediction should have been > actual, so error > 0
        assert error > 0, f"Expected positive error (over-prediction), got {error}"

        # Predict after — should be lower
        pred_after = scorer.predict(fv)
        assert pred_after < pred_before, f"Prediction should decrease after low outcome. Before={pred_before}, After={pred_after}"

        # Weights should have decreased
        stats = scorer.get_stats()
        assert stats["features_with_samples"] >= 3
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_learned_scorer_save_and_reload():
    """Weights should persist across scorer instances."""
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")

        # First instance: update weights
        scorer1 = LearnedScorer(db_path, learning_rate=0.1)
        scorer1.load()

        fv = FeatureVector()
        fv.set("pain_point_count", 3.0)
        fv.set("type_build_feature", 1.0)
        scorer1.update(fv, actual_outcome=5.0)
        scorer1.save()

        # Second instance: load and predict
        scorer2 = LearnedScorer(db_path, learning_rate=0.1)
        scorer2.load()

        pred1 = scorer1.predict(fv)
        pred2 = scorer2.predict(fv)
        assert pred1 == pred2, f"Predictions should match after reload. scorer1={pred1}, scorer2={pred2}"

        stats = scorer2.get_stats()
        assert stats["features_with_samples"] >= 2
        assert stats["total_samples"] >= 2
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_learned_scorer_converges_after_many_updates():
    """After many updates with consistent outcomes, predictions should converge."""
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        scorer = LearnedScorer(db_path, learning_rate=0.05)
        scorer.load()

        fv = FeatureVector()
        fv.set("pain_point_count", 3.0)
        fv.set("buying_signal_count", 2.0)
        fv.set("type_build_feature", 1.0)

        # Run 100 updates with consistent outcome = 30
        TARGET = 30.0
        for _ in range(100):
            scorer.update(fv, actual_outcome=TARGET)

        # After convergence, prediction should be close to target
        prediction = scorer.predict(fv)
        assert abs(prediction - TARGET) < 10, f"Should converge to {TARGET}, got {prediction} (diff {abs(prediction - TARGET):.2f})"

        # All features should now have enough samples
        stats = scorer.get_stats()
        assert stats["features_with_enough_samples"] >= 3
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_learned_scorer_high_outcome_increases_weights():
    """Update with high outcome should increase weights for present features."""
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        scorer = LearnedScorer(db_path, learning_rate=0.1)
        scorer.load()

        fv = FeatureVector()
        fv.set("pricing_complaint_count", 2.0)
        fv.set("type_launch_campaign", 1.0)

        pred_before = scorer.predict(fv)

        # Update with very high outcome (model under-predicted)
        scorer.update(fv, actual_outcome=95.0)

        pred_after = scorer.predict(fv)
        assert pred_after > pred_before, f"Prediction should increase after high outcome. Before={pred_before}, After={pred_after}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_learned_scorer_clamps_predictions_to_0_100():
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        scorer = LearnedScorer(db_path)
        scorer.load()

        # Huge feature values → should clamp at 100
        fv = FeatureVector()
        fv.set("pain_point_count", 100.0)
        fv.set("buying_signal_count", 100.0)
        fv.set("opportunity_score", 100.0)
        fv.set("type_build_feature", 1.0)
        fv.set("priority_P0", 1.0)
        fv.set("impact_high", 1.0)

        prediction = scorer.predict(fv)
        assert prediction == 100.0, f"Should clamp at 100, got {prediction}"

        # Zero features → should be just bias, clamped to ≥ 0
        fv_zero = FeatureVector()
        pred_zero = scorer.predict(fv_zero)
        assert pred_zero >= 0
        assert pred_zero <= 100
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_learned_scorer_get_feature_importance():
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        scorer = LearnedScorer(db_path)
        scorer.load()

        # Update a few features
        fv1 = FeatureVector()
        fv1.set("pain_point_count", 3.0)
        fv1.set("type_build_feature", 1.0)
        scorer.update(fv1, actual_outcome=50.0)

        fv2 = FeatureVector()
        fv2.set("buying_signal_count", 2.0)
        fv2.set("type_launch_campaign", 1.0)
        scorer.update(fv2, actual_outcome=20.0)

        importance = scorer.get_feature_importance()
        assert len(importance) >= 4  # at least 4 features touched

        # Should be sorted by absolute weight (descending)
        abs_weights = [abs(fi["weight"]) for fi in importance]
        assert abs_weights == sorted(abs_weights, reverse=True)

        # Each entry should have all required fields
        for fi in importance:
            assert "feature" in fi
            assert "weight" in fi
            assert "baseline" in fi
            assert "samples" in fi
            assert "delta_from_baseline" in fi
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ─── End-to-end: extract → predict → update → predict ─────────────────

def test_phase6_end_to_end_pipeline():
    """Verify the full feature extract → predict → update cycle works."""
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")

        # Setup: an item with rich metadata + a decision targeting it
        item = make_item("HubSpot pricing is insane", "http://1.com", body="Need cheaper alternative",
                          source="hacker_news", source_name="Hacker News")
        item.metadata["pain_points"] = [{"category": "pricing", "severity": "high"}]
        item.metadata["buying_signals"] = [{"type": "budget", "confidence": 0.8}]
        item.metadata["competitor_mentions"] = [{"competitor": "hubspot", "signal": "pricing_complaint"}]
        item.metadata["sentiment"] = "negative"
        item.metadata["authority_score"] = 90
        item.metadata["domain_signals"] = {
            "saas": {"signals": ["pricing_complaint"], "severity": "high", "severity_score": 3}
        }

        decision = {
            "id": "dec_test123",
            "type": "build_feature",
            "priority": "P0",
            "target": "hubspot",
            "expected_impact": "high",
            "evidence": [{"item_id": item.id, "title": "t", "url": "u", "source": "HN"}],
        }

        # Phase 6 pipeline
        extractor = FeatureExtractor()
        scorer = LearnedScorer(db_path, learning_rate=0.05)
        scorer.load()

        # Extract features
        fv = extractor.extract(decision, [item])
        assert len(fv.features) >= 10  # rich feature vector

        # Initial prediction (cold-start, uses baseline)
        initial_pred = scorer.predict(fv)
        assert 0 <= initial_pred <= 100

        # Simulate 20 outcome observations (some high, some low)
        outcomes = [10, 15, 8, 20, 12, 18, 5, 25, 14, 11, 9, 16, 13, 7, 22, 19, 17, 6, 21, 12]
        for outcome in outcomes:
            scorer.update(fv, actual_outcome=float(outcome))

        # Save and reload
        scorer.save()
        scorer_reloaded = LearnedScorer(db_path, learning_rate=0.05)
        scorer_reloaded.load()

        # Predictions should match
        pred1 = scorer.predict(fv)
        pred2 = scorer_reloaded.predict(fv)
        assert pred1 == pred2

        # After 20 updates, features should have enough samples to be "learned"
        stats = scorer_reloaded.get_stats()
        assert stats["features_with_enough_samples"] >= 5

        # Feature importance should be available
        importance = scorer_reloaded.get_feature_importance()
        assert len(importance) >= 5

        # All features touched should have samples >= 20
        for fi in importance:
            if fi["feature"] in fv.features:
                assert fi["samples"] >= 20, f"Feature {fi['feature']} should have 20+ samples, got {fi['samples']}"

        # MAE should be reasonable (< 30 = model is learning the pattern)
        avg_outcome = sum(outcomes) / len(outcomes)
        final_pred = scorer_reloaded.predict(fv)
        mae = abs(final_pred - avg_outcome)
        # Should be closer to the average outcome than the initial prediction was
        initial_error = abs(initial_pred - avg_outcome)
        assert mae < initial_error or mae < 20, (
            f"Model should improve. Initial error: {initial_error:.2f}, "
            f"final error: {mae:.2f}, avg outcome: {avg_outcome:.2f}, "
            f"final pred: {final_pred:.2f}"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
