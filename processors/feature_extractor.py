"""
Feature Extractor — converts a decision + its evidence items into a
feature vector for the LearnedScorer.

Each decision becomes a sparse feature vector with ~25 features:

  Counting features (from evidence items):
    pain_point_count          — total pain points across evidence
    buying_signal_count       — total buying signals
    seeking_alternative_count — users seeking alternatives
    pricing_complaint_count   — pricing complaints
    churn_mention_count       — churn signals
    positive_sentiment_count  — items with positive sentiment
    negative_sentiment_count  — items with negative sentiment
    evidence_count            — number of evidence items
    source_diversity          — distinct sources backing the decision

  Continuous features:
    avg_authority_score       — mean authority_score of evidence (0-100)
    opportunity_score         — heuristic opportunity (0-100)
    threat_score              — heuristic threat (0-100)
    competitor_weakness       — heuristic weakness (0-100)
    trend_score               — heuristic trend (0-100)
    avg_severity_score        — domain signal severity (0 if none, 1 low, 2 med, 3 high)

  One-hot features (decision metadata):
    type_build_feature
    type_launch_campaign
    type_write_content
    type_reach_out
    type_monitor_competitor
    type_investigate
    priority_P0
    priority_P1
    priority_P2
    priority_P3
    impact_high
    impact_medium
    impact_low
    has_urgency               — 1 if urgency_hours is set, else 0

  Domain features (from evidence items):
    saas_high_severity_count
    cybersecurity_high_severity_count
    ecommerce_high_severity_count

The feature vector is a dict {feature_name: value}. The LearnedScorer
stores one weight per feature name.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from core.models import ProcessedItem


# Baseline weights — approximate the current heuristic formula.
# These are used as the starting point before any learning happens,
# and as the fallback when a feature has too few samples (cold start).
BASELINE_WEIGHTS: dict[str, float] = {
    # Counting features (mirror current opportunity_score formula)
    "pain_point_count":          15.0,   # was: pain_points * 15
    "buying_signal_count":       20.0,   # was: buying_signals * 20
    "seeking_alternative_count": 25.0,   # was: seeking_alternatives * 25
    "pricing_complaint_count":   20.0,
    "churn_mention_count":       18.0,
    "positive_sentiment_count":  -5.0,   # positive sentiment about competitor = bad for us
    "negative_sentiment_count":  10.0,
    "evidence_count":             2.0,   # more evidence = more reliable signal
    "source_diversity":          10.0,   # multiple sources = stronger signal

    # Continuous features
    "avg_authority_score":       0.3,    # 0-100, so weight ~0.3 to scale to 0-30
    "opportunity_score":         0.4,    # 0-100, weight 0.4 → 0-40 contribution
    "threat_score":             -0.2,    # high threat = lower our ROI (we're behind)
    "competitor_weakness":       0.3,
    "trend_score":               0.3,
    "avg_severity_score":        8.0,

    # Decision type one-hot (scaled to contribute 0-30 to score)
    "type_build_feature":       30.0,
    "type_launch_campaign":     20.0,
    "type_write_content":       15.0,
    "type_reach_out":           22.0,
    "type_monitor_competitor":   5.0,
    "type_investigate":          8.0,

    # Priority one-hot (P0 > P1 > P2 > P3)
    "priority_P0":              15.0,
    "priority_P1":              10.0,
    "priority_P2":               5.0,
    "priority_P3":               2.0,

    # Impact one-hot
    "impact_high":              12.0,
    "impact_medium":             6.0,
    "impact_low":                2.0,

    # Binary
    "has_urgency":               5.0,

    # Domain features
    "saas_high_severity_count":         12.0,
    "cybersecurity_high_severity_count": 10.0,
    "ecommerce_high_severity_count":     10.0,
}

# Initial bias — approximates the average outcome when all features are zero
BASELINE_BIAS: float = 10.0

# Cold-start threshold — features with fewer than this many samples use baseline
COLD_START_SAMPLES: int = 5


@dataclass
class FeatureVector:
    """Sparse feature vector for a single decision."""
    features: dict[str, float] = field(default_factory=dict)

    def add(self, name: str, value: float) -> None:
        """Add a feature value. Accumulates if feature already exists."""
        if value != 0:
            self.features[name] = self.features.get(name, 0.0) + value

    def set(self, name: str, value: float) -> None:
        """Set a feature value (overwrite)."""
        if value != 0:
            self.features[name] = value

    def to_dict(self) -> dict[str, float]:
        return dict(self.features)

    @property
    def names(self) -> list[str]:
        return list(self.features.keys())


class FeatureExtractor:
    """Extracts feature vectors from decisions + their evidence items."""

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    def extract(self, decision: dict, items: list[ProcessedItem]) -> FeatureVector:
        """Extract a feature vector for a single decision.

        Args:
            decision: decision dict from DecisionEngine
            items: all ProcessedItems (used to look up evidence items by ID)

        Returns:
            FeatureVector with named features
        """
        fv = FeatureVector()

        # Index items by ID for fast evidence lookup
        items_by_id = {item.id: item for item in items}

        # Get evidence items
        evidence = decision.get("evidence", [])
        evidence_items = []
        for e in evidence:
            item_id = e.get("item_id", "")
            if item_id in items_by_id:
                evidence_items.append(items_by_id[item_id])

        # ─── Counting features ──────────────────────────────────────────
        pain_count = 0
        buying_count = 0
        seeking_count = 0
        pricing_count = 0
        churn_count = 0
        positive_sent = 0
        negative_sent = 0
        saas_high = 0
        cyber_high = 0
        ecommerce_high = 0
        authority_scores: list[float] = []
        severity_scores: list[float] = []
        sources: set[str] = set()

        for item in evidence_items:
            # Pain points
            pain_points = item.metadata.get("pain_points", [])
            pain_count += len(pain_points)

            # Buying signals
            buying_signals = item.metadata.get("buying_signals", [])
            buying_count += len(buying_signals)

            # Competitor mentions (seeking alternatives, pricing complaints)
            for cm in item.metadata.get("competitor_mentions", []):
                signal = cm.get("signal", "")
                if signal == "seeking_alternative":
                    seeking_count += 1
                elif signal == "pricing_complaint":
                    pricing_count += 1

            # Sentiment
            sentiment = item.metadata.get("sentiment", "neutral")
            if sentiment == "positive":
                positive_sent += 1
            elif sentiment == "negative":
                negative_sent += 1

            # Authority score
            auth = item.metadata.get("authority_score")
            if auth is not None:
                authority_scores.append(float(auth))

            # Source diversity
            sources.add(item.source_name or item.source or "")

            # Domain signals
            domain_signals = item.metadata.get("domain_signals", {})
            for domain_name, ds_data in domain_signals.items():
                severity = ds_data.get("severity", "none")
                sev_score = {"high": 3.0, "medium": 2.0, "low": 1.0, "none": 0.0}.get(severity, 0.0)
                severity_scores.append(sev_score)
                if severity == "high":
                    if domain_name == "saas":
                        saas_high += 1
                    elif domain_name == "cybersecurity":
                        cyber_high += 1
                    elif domain_name == "ecommerce":
                        ecommerce_high += 1

        # Add counting features
        fv.set("pain_point_count", float(pain_count))
        fv.set("buying_signal_count", float(buying_count))
        fv.set("seeking_alternative_count", float(seeking_count))
        fv.set("pricing_complaint_count", float(pricing_count))
        fv.set("churn_mention_count", float(churn_count))
        fv.set("positive_sentiment_count", float(positive_sent))
        fv.set("negative_sentiment_count", float(negative_sent))
        fv.set("evidence_count", float(len(evidence_items)))
        fv.set("source_diversity", float(len(sources)))

        # Continuous features
        if authority_scores:
            fv.set("avg_authority_score", sum(authority_scores) / len(authority_scores))
        if severity_scores:
            fv.set("avg_severity_score", sum(severity_scores) / len(severity_scores))

        # Pull heuristic scores from the item carrying _scores
        # (Find any item with _scores in metadata — usually items[0])
        scores_data = None
        for item in items:
            if "_scores" in item.metadata:
                scores_data = item.metadata["_scores"]
                break

        target = decision.get("target", "")
        if scores_data:
            # Find this target in company_scores or topic_scores
            for cs in scores_data.get("company_scores", []):
                if cs.get("entity", "").lower() == target.lower():
                    fv.set("opportunity_score", float(cs.get("opportunity_score", 0)))
                    fv.set("threat_score", float(cs.get("threat_score", 0)))
                    fv.set("competitor_weakness", float(cs.get("competitor_weakness_score", 0)))
                    break
            else:
                for ts in scores_data.get("topic_scores", []):
                    if ts.get("entity", "").lower() == target.lower():
                        fv.set("opportunity_score", float(ts.get("opportunity_score", 0)))
                        fv.set("trend_score", float(ts.get("trend_score", 0)))
                        break

        # Decision type one-hot
        dtype = decision.get("type", "")
        fv.set(f"type_{dtype}", 1.0)

        # Priority one-hot
        priority = decision.get("priority", "")
        fv.set(f"priority_{priority}", 1.0)

        # Impact one-hot
        impact = decision.get("expected_impact", "")
        fv.set(f"impact_{impact}", 1.0)

        # Urgency binary
        if decision.get("urgency_hours"):
            fv.set("has_urgency", 1.0)

        # Domain features
        fv.set("saas_high_severity_count", float(saas_high))
        fv.set("cybersecurity_high_severity_count", float(cyber_high))
        fv.set("ecommerce_high_severity_count", float(ecommerce_high))

        return fv
