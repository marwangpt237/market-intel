"""
Decision Engine — Phase 4 module.

Takes scoring output (`_scores`) + entity graph (`_entity_graph`) and produces
a ranked list of actionable decisions. Each decision has:

  - id: stable hash for tracking
  - type: build_feature | launch_campaign | write_content | reach_out | monitor_competitor | investigate
  - priority: P0 (critical) | P1 (high) | P2 (medium) | P3 (low)
  - target: which entity (company / topic) the action targets
  - rationale: human-readable explanation citing concrete evidence
  - expected_impact: estimated effect (high / medium / low)
  - urgency: hours_until_window_closes (None = no deadline)
  - evidence: list of item IDs + signal types backing this decision
  - suggested_action: short directive ("Build feature X before competitor Y")

This is rule-based — no AI / LLM calls. Rules map score combinations to
decision templates. The Learning Engine later adjusts rule thresholds
based on outcome data.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


# Priority weights — higher = more urgent
_PRIORITY_WEIGHTS = {
    "P0": 100,
    "P1": 75,
    "P2": 50,
    "P3": 25,
}


class DecisionEngine(BaseProcessor):
    name = "decision_engine"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        # Thresholds (can be overridden by config or learning engine)
        self._thresholds = {
            "opportunity_high": self._config.get("opportunity_high", 60),
            "opportunity_medium": self._config.get("opportunity_medium", 35),
            "threat_high": self._config.get("threat_high", 60),
            "threat_medium": self._config.get("threat_medium", 35),
            "weakness_high": self._config.get("weakness_high", 50),
            "trend_hot": self._config.get("trend_hot", 60),
            "trend_rising": self._config.get("trend_rising", 35),
            "min_evidence": self._config.get("min_evidence", 2),
        }
        # Learning weights (override thresholds)
        if "weights" in self._config:
            self._thresholds.update(self._config["weights"])

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        if not items:
            return items

        # Find the item carrying the scores + graph
        scores_data = None
        graph_data = None
        for item in items:
            if scores_data is None and "_scores" in item.metadata:
                scores_data = item.metadata["_scores"]
            if graph_data is None and "_entity_graph" in item.metadata:
                graph_data = item.metadata["_entity_graph"]
            if scores_data and graph_data:
                break

        if not scores_data:
            self._logger.info("No scores available — skipping decision engine")
            return items

        company_scores = scores_data.get("company_scores", [])
        topic_scores = scores_data.get("topic_scores", [])

        decisions: list[dict] = []

        # 1. Build-feature decisions from company opportunities
        for cs in company_scores:
            decisions.extend(self._decide_for_company(cs, items))

        # 2. Write-content decisions from trending topics
        for ts in topic_scores:
            decisions.extend(self._decide_for_topic(ts, items))

        # 3. Competitor-monitor decisions from threats
        for cs in company_scores:
            if cs.get("threat_score", 0) >= self._thresholds["threat_medium"]:
                decisions.extend(self._decide_monitor_competitor(cs))

        # Dedup decisions by stable ID
        seen: set[str] = set()
        unique: list[dict] = []
        for d in decisions:
            if d["id"] not in seen:
                seen.add(d["id"])
                unique.append(d)

        # Sort by priority weight (desc), then by expected impact
        impact_weight = {"high": 3, "medium": 2, "low": 1}
        unique.sort(
            key=lambda d: (_PRIORITY_WEIGHTS.get(d["priority"], 0), impact_weight.get(d["expected_impact"], 0)),
            reverse=True,
        )

        # Stash on first item
        items[0].metadata["_decisions"] = {
            "decisions": unique,
            "total": len(unique),
            "by_priority": {
                p: len([d for d in unique if d["priority"] == p])
                for p in _PRIORITY_WEIGHTS
            },
            "by_type": self._count_by_type(unique),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "thresholds": dict(self._thresholds),
        }

        self._logger.info(
            f"Decision engine: {len(unique)} decisions generated",
            extra=items[0].metadata["_decisions"]["by_priority"],
        )
        return items

    # ─── Decision rules ──────────────────────────────────────────────────

    def _decide_for_company(self, cs: dict, items: list[ProcessedItem]) -> list[dict]:
        """Generate decisions for a single company score record."""
        decisions: list[dict] = []
        company = cs.get("entity", "")
        opp = cs.get("opportunity_score", 0)
        threat = cs.get("threat_score", 0)
        weakness = cs.get("competitor_weakness_score", 0)
        data = cs.get("data", {})

        # Rule A: High opportunity + high weakness → Build feature to capture dissatisfied users
        if opp >= self._thresholds["opportunity_high"] and weakness >= self._thresholds["weakness_high"]:
            decisions.append(self._make_decision(
                decision_type="build_feature",
                priority="P0",
                target=company,
                rationale=(
                    f"Build an alternative for {company} — opportunity={opp}/100, "
                    f"weakness={weakness}/100. {data.get('seeking_alternatives', 0)} users "
                    f"actively seeking alternatives, {data.get('pricing_complaints', 0)} "
                    f"pricing complaints, {data.get('pain_points', 0)} pain points cited. "
                    f"No competitor currently satisfies this demand."
                ),
                expected_impact="high",
                suggested_action=(
                    f"Build a {company}-alternative that solves pricing & usability pain "
                    f"before another competitor captures these users."
                ),
                evidence=self._collect_evidence(items, company=company),
            ))

        # Rule B: Medium opportunity → Launch targeted campaign
        elif opp >= self._thresholds["opportunity_medium"]:
            decisions.append(self._make_decision(
                decision_type="launch_campaign",
                priority="P1",
                target=company,
                rationale=(
                    f"Capture dissatisfied {company} users — opportunity={opp}/100. "
                    f"{data.get('pain_points', 0)} pain points, "
                    f"{data.get('buying_signals', 0)} buying signals detected."
                ),
                expected_impact="medium",
                suggested_action=(
                    f"Launch comparison campaign targeting '{company} alternative' "
                    f"search intent. Highlight pain-point resolutions."
                ),
                evidence=self._collect_evidence(items, company=company),
            ))

        # Rule C: Reach out to high-intent buyers
        if data.get("buying_signals", 0) >= 3:
            decisions.append(self._make_decision(
                decision_type="reach_out",
                priority="P1",
                target=company,
                rationale=(
                    f"{data.get('buying_signals', 0)} buying signals detected around {company}. "
                    f"Users are in active evaluation mode — direct outreach has high conversion probability."
                ),
                expected_impact="medium",
                suggested_action=(
                    f"Personalized outreach to {data['buying_signals']} prospects discussing {company}. "
                    f"Offer demo, comparison sheet, or migration help."
                ),
                evidence=self._collect_evidence(items, company=company, signal="buying"),
            ))

        return decisions

    def _decide_for_topic(self, ts: dict, items: list[ProcessedItem]) -> list[dict]:
        """Generate write-content decisions for trending topics."""
        decisions: list[dict] = []
        topic = ts.get("entity", "")
        trend_score = ts.get("trend_score", 0)
        opp = ts.get("opportunity_score", 0)
        data = ts.get("data", {})
        trend_label = data.get("trend", "stable")

        if trend_score >= self._thresholds["trend_hot"] and trend_label in ("hot", "rising", "emerging"):
            decisions.append(self._make_decision(
                decision_type="write_content",
                priority="P1" if opp >= self._thresholds["opportunity_medium"] else "P2",
                target=topic,
                rationale=(
                    f"Topic '{topic}' is {trend_label} — trend_score={trend_score}/100, "
                    f"{data.get('mentions', 0)} mentions, "
                    f"{data.get('pain_points', 0)} pain points raised. "
                    f"Content published now will ride the rising wave."
                ),
                expected_impact="high" if trend_label == "hot" else "medium",
                suggested_action=(
                    f"Publish a deep-dive on '{topic}' within 7 days. "
                    f"Address the {data.get('pain_points', 0)} documented pain points."
                ),
                evidence=self._collect_evidence(items, topic=topic),
                urgency_hours=168,  # 7 days
            ))

        return decisions

    def _decide_monitor_competitor(self, cs: dict) -> list[dict]:
        """Threat-driven: add competitor to watchlist."""
        company = cs.get("entity", "")
        threat = cs.get("threat_score", 0)
        priority = "P1" if threat >= self._thresholds["threat_high"] else "P2"

        return [self._make_decision(
            decision_type="monitor_competitor",
            priority=priority,
            target=company,
            rationale=(
                f"Competitor {company} shows momentum — threat_score={threat}/100, "
                f"{cs.get('data', {}).get('mentions', 0)} mentions, "
                f"{cs.get('data', {}).get('positive_sentiment', 0)} positive sentiment items."
            ),
            expected_impact="low",
            suggested_action=(
                f"Add {company} to weekly watchlist. Track: new feature releases, "
                f"pricing changes, leadership moves, funding announcements."
            ),
            evidence=[],
        )]

    # ─── Helpers ─────────────────────────────────────────────────────────

    def _make_decision(
        self,
        decision_type: str,
        priority: str,
        target: str,
        rationale: str,
        expected_impact: str,
        suggested_action: str,
        evidence: list[dict] | None = None,
        urgency_hours: int | None = None,
    ) -> dict:
        """Build a decision dict with a stable ID."""
        id_source = f"{decision_type}|{target}|{priority}"
        decision_id = "dec_" + hashlib.sha1(id_source.encode("utf-8")).hexdigest()[:12]
        return {
            "id": decision_id,
            "type": decision_type,
            "priority": priority,
            "target": target,
            "rationale": rationale,
            "expected_impact": expected_impact,
            "urgency_hours": urgency_hours,
            "suggested_action": suggested_action,
            "evidence": evidence or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def _collect_evidence(
        self,
        items: list[ProcessedItem],
        company: str | None = None,
        topic: str | None = None,
        signal: str | None = None,
    ) -> list[dict]:
        """Find concrete items that back a decision."""
        evidence: list[dict] = []
        for item in items[:200]:  # cap for performance
            entities = item.metadata.get("entities", {})
            companies = entities.get("companies", [])
            cluster_label = item.metadata.get("cluster_label", "")

            if company and company not in companies:
                continue
            if topic and cluster_label != topic:
                continue
            if signal == "buying" and not item.metadata.get("buying_signals"):
                continue

            evidence.append({
                "item_id": item.id,
                "title": item.title[:120],
                "url": item.url,
                "source": item.source_name,
            })
            if len(evidence) >= 5:
                break
        return evidence

    @staticmethod
    def _count_by_type(decisions: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in decisions:
            counts[d["type"]] = counts.get(d["type"], 0) + 1
        return counts
