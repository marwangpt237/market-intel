"""
Moat Metrics Report — answers the 7 investor questions.

This is not architecture. This is measurement of the moat.

1. How many data sources do you own?
   → CollectorRegistry count + distinct sources in archive

2. How many Algerian businesses are indexed?
   → Count distinct companies in entities table + claim_store entities

3. How many products?
   → Count distinct product categories in algeria metadata + product_intelligence

4. How many historical observations?
   → Archive total items + daily breakdown + date range

5. How many decisions were validated?
   → Claim store counts by validation status + decision ledger stats

6. How accurate are your recommendations?
   → Learning engine outcome data (MAE, outcome-vs-prediction)

7. How difficult is it for a competitor to reproduce your dataset?
   → Qualitative score based on: data sources, historical depth, collector count, validation coverage

Output: reports/moat_metrics_<YYYY-MM-DD>_<run_id>.md
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from core.models import ProcessedItem
from core.logger import get_logger
from reports.base import BaseReportGenerator


class MoatMetricsReportGenerator(BaseReportGenerator):
    """Measures the moat — proprietary data that competitors cannot reproduce."""

    name = "moat_metrics"

    def __init__(self, config: dict):
        super().__init__(config)
        self._output_path = Path(config.get("output_path", "reports/"))
        self._db_path = config.get("storage", {}).get("path", "data/market_intel.db")
        self._archive_db_path = config.get("storage", {}).get(
            "archive_path",
            self._db_path.replace(".db", "_archive.db")
        )

    def _generate(self, items: list[ProcessedItem], run_id: str) -> str:
        self._output_path.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        # Gather all metrics
        metrics = self._gather_all_metrics(items)

        lines: list[str] = []
        lines.append(f"# Moat Metrics Report — {date_str}")
        lines.append("")
        lines.append(f"_Generated: {now.isoformat()} | Run: `{run_id}`_")
        lines.append("")
        lines.append("> **The moat is proprietary data, not software.**")
        lines.append("> These metrics answer the questions investors will ask.")
        lines.append("> Every month of collecting + archiving increases the value more than another month of architecture.")
        lines.append("")

        # ─── Executive Summary ───────────────────────────────────────────
        lines.append("## Executive Summary")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Data sources (collectors) | **{metrics['collector_count']}** |")
        lines.append(f"| Algerian businesses indexed | **{metrics['business_count']:,}** |")
        lines.append(f"| Products tracked | **{metrics['product_count']:,}** |")
        lines.append(f"| Historical observations (archived) | **{metrics['archive_total']:,}** |")
        lines.append(f"| Validated decisions | **{metrics['validated_claims']:,}** |")
        lines.append(f"| Recommendation accuracy (MAE) | **{metrics['mae']:.1f}/100** |")
        lines.append(f"| Reproducibility difficulty | **{metrics['reproducibility_score']}/10** |")
        lines.append(f"| Data archive span | **{metrics['archive_span_days']} days** |")
        lines.append("")

        # ─── Q1: How many data sources do you own? ───────────────────────
        lines.append("## 1. How many data sources do you own?")
        lines.append("")
        lines.append(f"**Answer: {metrics['collector_count']} registered collectors**")
        lines.append("")
        lines.append(f"- Registered collectors: {metrics['collector_count']}")
        lines.append(f"- Distinct sources in archive: {metrics['archive_distinct_sources']}")
        lines.append(f"- Distinct source names: {metrics['archive_distinct_source_names']}")
        lines.append("")

        if metrics.get("collectors_by_country"):
            lines.append("**By country:**")
            lines.append("")
            lines.append("| Country | Collectors |")
            lines.append("|---------|-----------|")
            for country, count in sorted(metrics["collectors_by_country"].items(), key=lambda x: -x[1]):
                lines.append(f"| {country} | {count} |")
            lines.append("")

        if metrics.get("collectors_by_category"):
            lines.append("**By category:**")
            lines.append("")
            lines.append("| Category | Collectors |")
            lines.append("|----------|-----------|")
            for category, count in sorted(metrics["collectors_by_category"].items(), key=lambda x: -x[1]):
                lines.append(f"| {category} | {count} |")
            lines.append("")

        if metrics.get("top_archive_sources"):
            lines.append("**Top sources by items collected:**")
            lines.append("")
            lines.append("| Source | Items Archived |")
            lines.append("|--------|---------------|")
            for source in metrics["top_archive_sources"][:10]:
                lines.append(f"| {source['source']} | {source['count']:,} |")
            lines.append("")

        # ─── Q2: How many Algerian businesses are indexed? ───────────────
        lines.append("## 2. How many Algerian businesses are indexed?")
        lines.append("")
        lines.append(f"**Answer: {metrics['business_count']:,} distinct businesses**")
        lines.append("")
        lines.append(f"- Distinct company entities extracted: {metrics['business_count']:,}")
        lines.append(f"- Distinct entities in validation store: {metrics['validated_entities']:,}")
        lines.append("")

        if metrics.get("top_companies"):
            lines.append("**Top indexed businesses:**")
            lines.append("")
            lines.append("| Business | Mentions |")
            lines.append("|----------|----------|")
            for company in metrics["top_companies"][:10]:
                lines.append(f"| {company['name']} | {company['count']} |")
            lines.append("")

        # ─── Q3: How many products? ──────────────────────────────────────
        lines.append("## 3. How many products?")
        lines.append("")
        lines.append(f"**Answer: {metrics['product_count']:,} distinct product categories tracked**")
        lines.append("")
        lines.append(f"- Product categories detected: {metrics['product_count']:,}")
        lines.append(f"- Total product mentions (all time): {metrics['product_mentions_total']:,}")
        lines.append("")

        if metrics.get("top_products"):
            lines.append("**Top products by mentions:**")
            lines.append("")
            lines.append("| Product Category | Mentions |")
            lines.append("|-----------------|----------|")
            for product in metrics["top_products"][:10]:
                lines.append(f"| {product['category']} | {product['count']} |")
            lines.append("")

        # ─── Q4: How many historical observations? ───────────────────────
        lines.append("## 4. How many historical observations?")
        lines.append("")
        lines.append(f"**Answer: {metrics['archive_total']:,} items archived permanently**")
        lines.append("")
        lines.append(f"- Total items in permanent archive: **{metrics['archive_total']:,}**")
        lines.append(f"- Archive date range: {metrics['archive_earliest']} → {metrics['archive_latest']}")
        lines.append(f"- Archive span: **{metrics['archive_span_days']} days**")
        lines.append("")

        if metrics.get("archive_daily_stats"):
            lines.append("**Last 7 days of collection:**")
            lines.append("")
            lines.append("| Date | Items Archived | Active Sources |")
            lines.append("|------|---------------|----------------|")
            for day in metrics["archive_daily_stats"]:
                lines.append(f"| {day['date']} | {day['items']:,} | {day['sources']} |")
            lines.append("")

        # ─── Q5: How many decisions were validated? ──────────────────────
        lines.append("## 5. How many decisions were validated?")
        lines.append("")
        lines.append(f"**Answer: {metrics['validated_claims']:,} validated claims**")
        lines.append("")
        lines.append(f"- Total claims in knowledge base: {metrics['total_claims']:,}")
        lines.append(f"- VERIFIED claims (3+ sources, confidence ≥ 0.70): {metrics['verified_claims']:,}")
        lines.append(f"- PROBABLE claims (2+ sources): {metrics['probable_claims']:,}")
        lines.append(f"- HYPOTHESIS claims (1 source): {metrics['hypothesis_claims']:,}")
        lines.append(f"- Total evidence pieces: {metrics['total_evidence']:,}")
        lines.append(f"- Decisions recorded in ledger: {metrics['decisions_recorded']:,}")
        lines.append(f"- Decisions with warnings: {metrics['decisions_with_warnings']:,}")
        lines.append("")

        # ─── Q6: How accurate are your recommendations? ──────────────────
        lines.append("## 6. How accurate are your recommendations?")
        lines.append("")
        if metrics['mae'] > 0:
            lines.append(f"**Answer: Mean Absolute Error = {metrics['mae']:.1f}/100**")
            lines.append("")
            lines.append(f"- MAE (prediction vs actual outcome): {metrics['mae']:.1f}/100")
            lines.append(f"- Outcomes observed: {metrics['outcomes_observed']:,}")
            lines.append(f"- Features with learned weights: {metrics['learned_features']:,}")
            lines.append(f"- Features with enough samples (≥5): {metrics['mature_features']:,}")
            lines.append("")
            if metrics['mae'] < 15:
                lines.append("> ✅ **Well-calibrated** — predictions are within 15 points of actual outcomes.")
            elif metrics['mae'] < 30:
                lines.append("> ⚠️ **Moderately calibrated** — more outcome data needed for tight predictions.")
            else:
                lines.append("> ⚠️ **Poorly calibrated** — need more outcome data. Fill in `metrics_input_template.json`.")
        else:
            lines.append("**Answer: Insufficient outcome data**")
            lines.append("")
            lines.append("> No outcomes have been recorded yet. To measure accuracy:")
            lines.append("> 1. Open `data/metrics_input_template.json`")
            lines.append("> 2. Fill in observed clicks/signups/conversions/revenue per action")
            lines.append("> 3. Change status from 'draft' to 'sent' or 'published'")
            lines.append("> 4. Next run, the Learning Engine will compute MAE")
        lines.append("")

        # ─── Q7: How difficult to reproduce? ─────────────────────────────
        lines.append("## 7. How difficult is it for a competitor to reproduce your dataset?")
        lines.append("")
        lines.append(f"**Answer: {metrics['reproducibility_score']}/10 (difficulty score)**")
        lines.append("")
        lines.append("Based on:")
        lines.append("")
        lines.append(f"- Collector count: {metrics['collector_count']} (each takes ~2-4 hours to build)")
        lines.append(f"- Algerian-specific collectors: {metrics['algerian_collector_count']}")
        lines.append(f"- Historical depth: {metrics['archive_span_days']} days of accumulated data")
        lines.append(f"- Total archived observations: {metrics['archive_total']:,}")
        lines.append(f"- Validated claims in knowledge graph: {metrics['total_claims']:,}")
        lines.append(f"- Algerian businesses indexed: {metrics['business_count']:,}")
        lines.append("")

        # Compute estimated reproduction effort
        hours_per_collector = 3
        total_collector_hours = metrics['collector_count'] * hours_per_collector
        days_of_collection = metrics['archive_span_days']
        lines.append(f"**Estimated reproduction effort for a competitor:**")
        lines.append("")
        lines.append(f"- Build {metrics['collector_count']} collectors: ~{total_collector_hours} hours")
        lines.append(f"- Accumulate {days_of_collection} days of historical data: **{days_of_collection} days (cannot be shortcut)**")
        lines.append(f"- Build validation engine + trust layer: ~40 hours")
        lines.append(f"- Build country pack (Darija NLP, wilayas, payments, seasonal): ~30 hours")
        lines.append("")
        if metrics['reproducibility_score'] >= 7:
            lines.append("> 🏆 **Strong moat** — historical data cannot be shortcut. A competitor would need")
            lines.append("> " + str(days_of_collection) + " days just to match your historical depth.")
        elif metrics['reproducibility_score'] >= 4:
            lines.append("> ⚡ **Building moat** — keep accumulating. The longer you run, the harder to reproduce.")
        else:
            lines.append("> ⚠️ **Weak moat** — need more collectors + more historical data. Focus on Priority 1.")
        lines.append("")

        # ─── Growth Trajectory ───────────────────────────────────────────
        lines.append("## Growth Trajectory")
        lines.append("")
        lines.append("**This month's targets (Priority 1):**")
        lines.append("")
        lines.append(f"- [ ] Expand collectors from {metrics['collector_count']} to 50+")
        lines.append(f"- [ ] Archive {max(10000, metrics['archive_total'] * 2):,}+ total items")
        lines.append(f"- [ ] Index {max(500, metrics['business_count'] * 2):,}+ Algerian businesses")
        lines.append(f"- [ ] Validate {max(200, metrics['total_claims'] * 2):,}+ claims")
        lines.append(f"- [ ] Record outcomes for 20+ actions (fill in metrics_input_template.json)")
        lines.append("")
        lines.append("**The moat grows every day the system runs.**")
        lines.append("")

        # ─── Footer ──────────────────────────────────────────────────────
        lines.append("---")
        lines.append("")
        lines.append("_Market-Intel — Moat Metrics. Software is the means; data is the end._")

        filepath = self._output_path / f"moat_metrics_{date_str}_{run_id}.md"
        filepath.write_text("\n".join(lines), encoding="utf-8")

        self._logger.info(f"Moat metrics report written to {filepath}")
        return str(filepath)

    def _gather_all_metrics(self, items: list[ProcessedItem]) -> dict:
        """Gather all moat metrics from various sources."""
        metrics: dict = {}

        # ─── Collector metrics ───────────────────────────────────────────
        try:
            # Trigger imports
            import collectors.marketplace.ouedkniss_collector  # noqa
            import collectors.marketplace.algeria_jobs_collector  # noqa
            import collectors.marketplace.algeria_forum_collector  # noqa
            import collectors.marketplace.algeria_gov_collector  # noqa
            from collectors.marketplace.base import CollectorRegistry
            registry_stats = CollectorRegistry.get_stats()
            metrics["collector_count"] = registry_stats.get("total_collectors", 0)
            metrics["collectors_by_country"] = registry_stats.get("by_country", {})
            metrics["collectors_by_category"] = registry_stats.get("by_category", {})
            metrics["algerian_collector_count"] = len(CollectorRegistry.list_by_country("DZ"))
        except Exception:
            metrics["collector_count"] = 0
            metrics["collectors_by_country"] = {}
            metrics["collectors_by_category"] = {}
            metrics["algerian_collector_count"] = 0

        # ─── Archive metrics ─────────────────────────────────────────────
        try:
            from storage.raw_archiver import RawDataArchiver
            archiver = RawDataArchiver(self._archive_db_path)
            archive_stats = archiver.get_stats()
            metrics["archive_total"] = archive_stats.get("total_items_archived", 0)
            metrics["archive_distinct_sources"] = archive_stats.get("total_distinct_sources", 0)
            metrics["archive_distinct_source_names"] = archive_stats.get("total_distinct_source_names", 0)
            metrics["archive_earliest"] = archive_stats.get("earliest_archive_date", "—")
            metrics["archive_latest"] = archive_stats.get("latest_archive_date", "—")
            metrics["top_archive_sources"] = archive_stats.get("top_sources", [])
            metrics["archive_daily_stats"] = archive_stats.get("daily_stats_last_7", [])

            # Compute span in days
            if archive_stats.get("earliest_archive_date") and archive_stats.get("latest_archive_date"):
                try:
                    earliest = datetime.fromisoformat(archive_stats["earliest_archive_date"])
                    latest = datetime.fromisoformat(archive_stats["latest_archive_date"])
                    metrics["archive_span_days"] = max(1, (latest - earliest).days)
                except Exception:
                    metrics["archive_span_days"] = 0
            else:
                metrics["archive_span_days"] = 0
        except Exception:
            metrics["archive_total"] = 0
            metrics["archive_distinct_sources"] = 0
            metrics["archive_distinct_source_names"] = 0
            metrics["archive_earliest"] = "—"
            metrics["archive_latest"] = "—"
            metrics["top_archive_sources"] = []
            metrics["archive_daily_stats"] = []
            metrics["archive_span_days"] = 0

        # ─── Business + product metrics (from working DB) ────────────────
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row

            # Count distinct companies in items metadata
            # metadata is JSON, so we search for "companies" in metadata
            # This is best-effort — for production, add a proper index
            all_items = conn.execute("SELECT metadata FROM items LIMIT 10000").fetchall()
            companies: Counter = Counter()
            products: Counter = Counter()
            for row in all_items:
                try:
                    meta = json.loads(row["metadata"] or "{}")
                    for company in meta.get("entities", {}).get("companies", []):
                        companies[company.lower()] += 1
                    # Algeria products
                    for product in meta.get("algeria", {}).get("products", []):
                        products[product.get("category", "unknown")] += 1
                except Exception:
                    continue

            metrics["business_count"] = len(companies)
            metrics["product_count"] = len(products)
            metrics["product_mentions_total"] = sum(products.values())
            metrics["top_companies"] = [{"name": k, "count": v} for k, v in companies.most_common(10)]
            metrics["top_products"] = [{"category": k, "count": v} for k, v in products.most_common(10)]

            conn.close()
        except Exception:
            metrics["business_count"] = 0
            metrics["product_count"] = 0
            metrics["product_mentions_total"] = 0
            metrics["top_companies"] = []
            metrics["top_products"] = []

        # ─── Validation metrics ──────────────────────────────────────────
        try:
            from validation.claim_store import ClaimStore
            store = ClaimStore(self._db_path)
            store_stats = store.get_stats()
            metrics["total_claims"] = store_stats.get("total_claims", 0)
            metrics["verified_claims"] = store_stats.get("by_status", {}).get("VERIFIED", 0)
            metrics["probable_claims"] = store_stats.get("by_status", {}).get("PROBABLE", 0)
            metrics["hypothesis_claims"] = store_stats.get("by_status", {}).get("HYPOTHESIS", 0)
            metrics["validated_claims"] = metrics["verified_claims"] + metrics["probable_claims"]
            metrics["total_evidence"] = store_stats.get("total_evidence_pieces", 0)

            # Count distinct entities in claim store
            all_claims = store.get_all_claims(limit=10000)
            entities = {claim.entity for claim in all_claims}
            metrics["validated_entities"] = len(entities)
        except Exception:
            metrics["total_claims"] = 0
            metrics["verified_claims"] = 0
            metrics["probable_claims"] = 0
            metrics["hypothesis_claims"] = 0
            metrics["validated_claims"] = 0
            metrics["total_evidence"] = 0
            metrics["validated_entities"] = 0

        # ─── Decision ledger metrics ─────────────────────────────────────
        try:
            from validation.decision_ledger import DecisionLedger
            ledger = DecisionLedger(self._db_path)
            ledger_stats = ledger.get_stats()
            metrics["decisions_recorded"] = ledger_stats.get("total_decisions", 0)
            metrics["decisions_with_warnings"] = ledger_stats.get("decisions_with_warnings", 0)
        except Exception:
            metrics["decisions_recorded"] = 0
            metrics["decisions_with_warnings"] = 0

        # ─── Learning metrics (accuracy) ─────────────────────────────────
        try:
            # Read from items metadata (Learning Engine output)
            learning_data = None
            for item in items:
                if "_learning" in item.metadata:
                    learning_data = item.metadata["_learning"]
                    break

            if learning_data and learning_data.get("learned_feature_weights"):
                learned = learning_data["learned_feature_weights"]
                metrics["mae"] = learned.get("mean_absolute_error", 0.0)
                metrics["outcomes_observed"] = learned.get("actions_updated", 0)
                model_stats = learned.get("model_stats", {})
                metrics["learned_features"] = model_stats.get("total_features", 0)
                metrics["mature_features"] = model_stats.get("features_with_enough_samples", 0)
            else:
                metrics["mae"] = 0.0
                metrics["outcomes_observed"] = 0
                metrics["learned_features"] = 0
                metrics["mature_features"] = 0
        except Exception:
            metrics["mae"] = 0.0
            metrics["outcomes_observed"] = 0
            metrics["learned_features"] = 0
            metrics["mature_features"] = 0

        # ─── Reproducibility score (0-10) ────────────────────────────────
        score = 0
        if metrics["collector_count"] >= 10:
            score += 2
        elif metrics["collector_count"] >= 5:
            score += 1
        if metrics["algerian_collector_count"] >= 5:
            score += 2
        elif metrics["algerian_collector_count"] >= 1:
            score += 1
        if metrics["archive_span_days"] >= 30:
            score += 2
        elif metrics["archive_span_days"] >= 7:
            score += 1
        if metrics["archive_total"] >= 5000:
            score += 2
        elif metrics["archive_total"] >= 1000:
            score += 1
        if metrics["total_claims"] >= 100:
            score += 1
        if metrics["business_count"] >= 100:
            score += 1
        metrics["reproducibility_score"] = min(10, score)

        return metrics
