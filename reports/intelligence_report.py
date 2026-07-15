"""
Intelligence report generator — transforms data into actionable insights.

Output format:
  "42 people asked for OSINT tools this week.
   18 complained about Maltego pricing.
   7 companies are actively evaluating alternatives."

Instead of listing every collected item, this report:
1. Summarizes trends (rising/hot/declining topics)
2. Quantifies pain points by category
3. Lists competitor mentions with signal types
4. Highlights buying signals with confidence scores
5. Extracts entity frequency (companies/products mentioned most)
6. Provides a "Key Insights" section with natural language summary
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from collections import Counter, defaultdict
from core.models import ProcessedItem
from core.logger import get_logger
from reports.base import BaseReportGenerator


class IntelligenceReportGenerator(BaseReportGenerator):
    name = "intelligence"

    def __init__(self, config: dict):
        super().__init__(config)
        self._output_path = Path(config.get("output_path", "reports/"))
        self._top_count: int = config.get("top_stories_count", 10)

    def _generate(self, items: list[ProcessedItem], run_id: str) -> str:
        self._output_path.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        lines: list[str] = []
        lines.append(f"# Market Intelligence Report — {date_str}")
        lines.append("")
        lines.append(f"_Generated: {now.isoformat()} | Run: `{run_id}`_")
        lines.append("")

        # ─── Key Insights (the actionable summary) ──────────────────────
        lines.append("## Key Insights")
        lines.append("")
        insights = self._generate_insights(items)
        for insight in insights:
            lines.append(f"- {insight}")
        lines.append("")

        # ─── Trend Summary ──────────────────────────────────────────────
        trend_summary = self._extract_trend_summary(items)
        if trend_summary:
            lines.append("## Trends")
            lines.append("")
            if trend_summary.get("hot"):
                lines.append(f"**🔥 Hot topics:** {', '.join(f'`{t}`' for t in trend_summary['hot'])}")
                lines.append("")
            if trend_summary.get("rising"):
                lines.append(f"**📈 Rising:** {', '.join(f'`{t}`' for t in trend_summary['rising'])}")
                lines.append("")
            if trend_summary.get("emerging"):
                lines.append(f"**✨ Emerging:** {', '.join(f'`{t}`' for t in trend_summary['emerging'])}")
                lines.append("")
            if trend_summary.get("declining"):
                lines.append(f"**📉 Declining:** {', '.join(f'`{t}`' for t in trend_summary['declining'])}")
                lines.append("")

        # ─── Pain Points ────────────────────────────────────────────────
        pain_summary = self._summarize_pain_points(items)
        if pain_summary:
            lines.append("## Pain Points")
            lines.append("")
            lines.append("| Category | Mentions | Severity | Example |")
            lines.append("|---|---|---|---|")
            for pp in pain_summary[:10]:
                example = pp["example"][:80].replace("|", "\\|")
                lines.append(f"| {pp['category']} | {pp['count']} | {pp['severity']} | {example} |")
            lines.append("")

        # ─── Competitor Mentions ────────────────────────────────────────
        competitor_summary = self._summarize_competitors(items)
        if competitor_summary:
            lines.append("## Competitor Intelligence")
            lines.append("")
            lines.append("| Competitor | Mentions | Signal Type | Category |")
            lines.append("|---|---|---|---|")
            for comp in competitor_summary:
                lines.append(f"| {comp['competitor']} | {comp['count']} | {comp['top_signal']} | {comp['category']} |")
            lines.append("")

            # Detailed competitor signals
            lines.append("### Detailed Signals")
            lines.append("")
            for item in items:
                mentions = item.metadata.get("competitor_mentions", [])
                if mentions:
                    for m in mentions[:3]:
                        lines.append(f"- **{m['competitor']}** ({m['signal']}): {item.title[:80]}")
                        lines.append(f"  _{m['context'][:120]}_")
                        lines.append(f"  [{item.url}]({item.url})")
            lines.append("")

        # ─── Buying Signals ─────────────────────────────────────────────
        buying_items = [item for item in items if item.metadata.get("buying_signals")]
        if buying_items:
            lines.append("## Buying Signals")
            lines.append("")
            lines.append(f"**{len(buying_items)} items with purchase intent detected.**")
            lines.append("")

            # Sort by buying_intent score
            buying_items.sort(key=lambda x: x.metadata.get("buying_intent", 0), reverse=True)
            lines.append("| Source | Title | Intent | Signal Type |")
            lines.append("|---|---|---|---|")
            for item in buying_items[:10]:
                intent = item.metadata.get("buying_intent", 0)
                signals = item.metadata.get("buying_signals", [])
                signal_types = ", ".join(set(s["type"] for s in signals))
                title = item.title[:60].replace("|", "\\|")
                lines.append(f"| {item.source_name} | [{title}]({item.url}) | {intent:.0%} | {signal_types} |")
            lines.append("")

        # ─── Entity Frequency ───────────────────────────────────────────
        entity_summary = self._summarize_entities(items)
        if entity_summary:
            lines.append("## Mentioned Entities")
            lines.append("")
            if entity_summary.get("companies"):
                lines.append("**Companies:** " + ", ".join(f"`{name}` ({count})" for name, count in entity_summary["companies"][:10]))
                lines.append("")
            if entity_summary.get("products"):
                lines.append("**Products:** " + ", ".join(f"`{name}` ({count})" for name, count in entity_summary["products"][:10]))
                lines.append("")

        # ─── Topic Clusters ─────────────────────────────────────────────
        clusters = self._summarize_clusters(items)
        if clusters:
            lines.append("## Topic Clusters")
            lines.append("")
            for cluster in clusters:
                lines.append(f"### {cluster['label']} ({cluster['count']} items)")
                for item in cluster["items"][:3]:
                    lines.append(f"- [{item.title}]({item.url})")
                if cluster["count"] > 3:
                    lines.append(f"- _...and {cluster['count'] - 3} more_")
                lines.append("")

        # ─── Collection Stats ───────────────────────────────────────────
        lines.append("## Collection Stats")
        lines.append("")
        sources = Counter(item.source for item in items)
        lines.append(f"- Total items: **{len(items)}**")
        lines.append(f"- Sources: {', '.join(f'{name} ({count})' for name, count in sources.most_common())}")
        lines.append(f"- Collectors: {len(sources)}")
        lines.append("")

        lines.append("---")
        lines.append(f"_Powered by [Market-Intel](https://github.com/marwannaili237/market-intel)_")

        content = "\n".join(lines)
        filepath = self._output_path / f"report_{date_str}.md"
        filepath.write_text(content, encoding="utf-8")

        self._logger.info(f"Intelligence report saved to {filepath}", extra={"file": str(filepath)})
        return str(filepath)

    def _generate_insights(self, items: list[ProcessedItem]) -> list[str]:
        """Generate natural language insights from the data."""
        insights: list[str] = []

        # Pain point count
        pain_items = [item for item in items if item.metadata.get("pain_points")]
        if pain_items:
            insights.append(f"**{len(pain_items)} items** expressed pain points or frustrations.")

        # Competitor mentions
        competitor_items = [item for item in items if item.metadata.get("competitor_mentions")]
        if competitor_items:
            all_comps = []
            for item in competitor_items:
                for m in item.metadata.get("competitor_mentions", []):
                    all_comps.append(m["competitor"])
            top_comp = Counter(all_comps).most_common(1)
            if top_comp:
                insights.append(f"**{len(competitor_items)} items** mentioned competitors. Most mentioned: `{top_comp[0][0]}` ({top_comp[0][1]}x).")

        # Buying signals
        buying_items = [item for item in items if item.metadata.get("buying_signals")]
        if buying_items:
            high_intent = [item for item in buying_items if item.metadata.get("buying_intent", 0) >= 0.7]
            insights.append(f"**{len(buying_items)} items** showed buying signals ({len(high_intent)} with high confidence).")

        # Pricing complaints
        pricing_items = []
        for item in items:
            for pp in item.metadata.get("pain_points", []):
                if pp.get("category") == "pricing":
                    pricing_items.append(item)
                    break
        if pricing_items:
            insights.append(f"**{len(pricing_items)} items** mentioned pricing concerns.")

        # Trending topics
        trend_summary = self._extract_trend_summary(items)
        if trend_summary and trend_summary.get("hot"):
            insights.append(f"**Hot topics:** {', '.join(trend_summary['hot'][:5])}")

        if not insights:
            insights.append("No significant intelligence signals detected in this collection run.")

        return insights

    def _extract_trend_summary(self, items: list[ProcessedItem]) -> dict:
        for item in items:
            ts = item.metadata.get("_trend_summary")
            if ts:
                return ts
        return {}

    def _summarize_pain_points(self, items: list[ProcessedItem]) -> list[dict]:
        pp_counter: Counter = Counter()
        pp_severity: dict[str, str] = {}
        pp_examples: dict[str, str] = {}

        for item in items:
            for pp in item.metadata.get("pain_points", []):
                cat = pp.get("category", "unknown")
                pp_counter[cat] += 1
                pp_severity[cat] = pp.get("severity", "medium")
                if cat not in pp_examples:
                    pp_examples[cat] = pp.get("context", "")[:100]

        return [
            {"category": cat, "count": count, "severity": pp_severity.get(cat, "medium"), "example": pp_examples.get(cat, "")}
            for cat, count in pp_counter.most_common()
        ]

    def _summarize_competitors(self, items: list[ProcessedItem]) -> list[dict]:
        comp_counter: Counter = Counter()
        comp_signals: dict[str, Counter] = defaultdict(Counter)
        comp_categories: dict[str, str] = {}

        for item in items:
            for m in item.metadata.get("competitor_mentions", []):
                comp = m["competitor"]
                comp_counter[comp] += 1
                comp_signals[comp][m["signal"]] += 1
                comp_categories[comp] = m.get("category", "unknown")

        return [
            {
                "competitor": comp,
                "count": count,
                "top_signal": comp_signals[comp].most_common(1)[0][0] if comp_signals[comp] else "mention",
                "category": comp_categories.get(comp, "unknown"),
            }
            for comp, count in comp_counter.most_common()
        ]

    def _summarize_entities(self, items: list[ProcessedItem]) -> dict:
        company_counter: Counter = Counter()
        product_counter: Counter = Counter()

        for item in items:
            entities = item.metadata.get("entities", {})
            for comp in entities.get("companies", []):
                company_counter[comp] += 1
            for prod in entities.get("products", []):
                product_counter[prod] += 1

        return {
            "companies": company_counter.most_common(15),
            "products": product_counter.most_common(10),
        }

    def _summarize_clusters(self, items: list[ProcessedItem]) -> list[dict]:
        clusters: dict[int, list[ProcessedItem]] = defaultdict(list)
        labels: dict[int, str] = {}

        for item in items:
            cid = item.metadata.get("cluster_id", -1)
            if cid >= 0:
                clusters[cid].append(item)
                labels[cid] = item.metadata.get("cluster_label", "unknown")

        return [
            {"label": labels[cid], "count": len(cluster_items), "items": cluster_items}
            for cid, cluster_items in sorted(clusters.items(), key=lambda x: len(x[1]), reverse=True)
            if len(cluster_items) >= 2
        ][:10]
