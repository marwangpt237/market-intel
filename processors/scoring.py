"""
Scoring engine — calculates opportunity, threat, trend, and competitor scores.

Produces decision-support output:
  "Build Feature X before Competitor Y does because 137 prospects
   requested it, demand is rising 18% weekly, and no competitor
   currently satisfies it."

Scores (0-100):
- Opportunity Score: how much unmet demand exists for a topic/feature
- Threat Score: how much competitive pressure is building
- Trend Score: how fast a topic is growing
- Competitor Score: how much competitor momentum exists
"""
from __future__ import annotations

from collections import Counter, defaultdict
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


class ScoringProcessor(BaseProcessor):
    name = "scoring"

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        # Aggregate data for scoring
        company_data: dict[str, dict] = defaultdict(lambda: {
            "mentions": 0,
            "pain_points": 0,
            "buying_signals": 0,
            "pricing_complaints": 0,
            "seeking_alternatives": 0,
            "positive_sentiment": 0,
            "negative_sentiment": 0,
        })

        topic_data: dict[str, dict] = defaultdict(lambda: {
            "mentions": 0,
            "pain_points": 0,
            "buying_signals": 0,
            "trend": "stable",
        })

        # Collect data per company and topic
        for item in items:
            entities = item.metadata.get("entities", {})
            companies = entities.get("companies", [])
            pain_points = item.metadata.get("pain_points", [])
            buying_signals = item.metadata.get("buying_signals", [])
            competitor_mentions = item.metadata.get("competitor_mentions", [])
            sentiment = item.metadata.get("sentiment", "neutral")
            cluster_label = item.metadata.get("cluster_label", "")

            for company in companies:
                company_data[company]["mentions"] += 1
                company_data[company]["pain_points"] += len(pain_points)
                company_data[company]["buying_signals"] += len(buying_signals)
                if sentiment == "positive":
                    company_data[company]["positive_sentiment"] += 1
                elif sentiment == "negative":
                    company_data[company]["negative_sentiment"] += 1

            for cm in competitor_mentions:
                comp = cm["competitor"]
                company_data[comp]["mentions"] += 1
                if cm.get("signal") == "pricing_complaint":
                    company_data[comp]["pricing_complaints"] += 1
                if cm.get("signal") == "seeking_alternative":
                    company_data[comp]["seeking_alternatives"] += 1

            if cluster_label and cluster_label != "uncategorized":
                topic_data[cluster_label]["mentions"] += 1
                topic_data[cluster_label]["pain_points"] += len(pain_points)
                topic_data[cluster_label]["buying_signals"] += len(buying_signals)
                topic_data[cluster_label]["trend"] = item.metadata.get("trend", "stable")

        # Calculate scores per company
        company_scores: list[dict] = []
        for company, data in company_data.items():
            # Opportunity score: high pain points + high buying signals = opportunity
            opportunity = min(100, (data["pain_points"] * 15 + data["buying_signals"] * 20 + data["seeking_alternatives"] * 25))

            # Threat score: high mentions + high positive sentiment = competitor is strong
            threat = min(100, (data["mentions"] * 5 + data["positive_sentiment"] * 15))

            # Competitor momentum: pricing complaints + seeking alternatives = weakness
            weakness = min(100, (data["pricing_complaints"] * 20 + data["seeking_alternatives"] * 15 + data["negative_sentiment"] * 10))

            company_scores.append({
                "entity": company,
                "type": "company",
                "opportunity_score": opportunity,
                "threat_score": threat,
                "competitor_weakness_score": weakness,
                "data": dict(data),
            })

        # Calculate scores per topic
        topic_scores: list[dict] = []
        for topic, data in topic_data.items():
            # Trend score: based on trend label + volume
            trend_multiplier = {"hot": 3.0, "rising": 2.0, "emerging": 2.5, "declining": 0.3, "stable": 1.0}.get(data["trend"], 1.0)
            trend_score = min(100, int(data["mentions"] * 5 * trend_multiplier))

            # Opportunity: pain points + buying signals in this topic
            opportunity = min(100, (data["pain_points"] * 15 + data["buying_signals"] * 20))

            topic_scores.append({
                "entity": topic,
                "type": "topic",
                "trend_score": trend_score,
                "opportunity_score": opportunity,
                "data": dict(data),
            })

        # Sort by opportunity score (highest first)
        company_scores.sort(key=lambda x: x["opportunity_score"], reverse=True)
        topic_scores.sort(key=lambda x: x["opportunity_score"], reverse=True)

        # Generate decision-support insights
        insights = self._generate_insights(company_scores, topic_scores)

        # Store on first item
        if items:
            items[0].metadata["_scores"] = {
                "company_scores": company_scores[:20],
                "topic_scores": topic_scores[:15],
                "insights": insights,
            }

        self._logger.info(
            f"Scoring: {len(company_scores)} companies, {len(topic_scores)} topics scored",
            extra={"companies": len(company_scores), "topics": len(topic_scores), "insights": len(insights)}
        )
        return items

    def _generate_insights(self, company_scores: list[dict], topic_scores: list[dict]) -> list[str]:
        """Generate natural-language decision-support insights."""
        insights: list[str] = []

        # Top opportunity companies
        for score in company_scores[:5]:
            if score["opportunity_score"] >= 30:
                data = score["data"]
                parts = []
                if data["pain_points"]:
                    parts.append(f"{data['pain_points']} pain points mentioned")
                if data["buying_signals"]:
                    parts.append(f"{data['buying_signals']} buying signals detected")
                if data["seeking_alternatives"]:
                    parts.append(f"{data['seeking_alternatives']} users seeking alternatives")
                if data["pricing_complaints"]:
                    parts.append(f"{data['pricing_complaints']} pricing complaints")

                if parts:
                    insights.append(
                        f"**{score['entity']}** — Opportunity score: {score['opportunity_score']}/100. "
                        f"{'; '.join(parts)}."
                    )

        # Top trending topics with opportunity
        for score in topic_scores[:5]:
            if score["trend_score"] >= 30:
                data = score["data"]
                trend_label = data.get("trend", "stable")
                insights.append(
                    f"**{score['entity']}** — Trend score: {score['trend_score']}/100 "
                    f"({trend_label}), {data['mentions']} mentions, "
                    f"{data['pain_points']} pain points, {data['buying_signals']} buying signals."
                )

        # Competitor weakness signals
        weak_competitors = [s for s in company_scores if s["competitor_weakness_score"] >= 30]
        for score in weak_competitors[:3]:
            data = score["data"]
            insights.append(
                f"**{score['entity']}** shows weakness — {data['pricing_complaints']} pricing complaints, "
                f"{data['seeking_alternatives']} users looking for alternatives. "
                f"Opportunity to capture dissatisfied users."
            )

        if not insights:
            insights.append("No significant scoring signals detected in this run.")

        return insights
