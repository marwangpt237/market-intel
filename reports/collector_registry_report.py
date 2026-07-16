"""
Collector Registry Report — lists all registered collectors + health + categories.

Shows:
  1. Registry summary (total collectors, by country, by category)
  2. All collectors table (name, country, category, entity types, reliability, health)
  3. Collectors by country (focused on Algeria)
  4. Collectors by category (news, classifieds, jobs, forum, government)
  5. Health summary (which collectors are healthy/degraded/down)
  6. Required credentials (which collectors need API keys)
  7. How to add a new collector (developer docs)

Output: reports/collector_registry_<YYYY-MM-DD>_<run_id>.md
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from core.models import ProcessedItem
from core.logger import get_logger
from reports.base import BaseReportGenerator


class CollectorRegistryReportGenerator(BaseReportGenerator):
    name = "collector_registry"

    def __init__(self, config: dict):
        super().__init__(config)
        self._output_path = Path(config.get("output_path", "reports/"))

    def _generate(self, items: list[ProcessedItem], run_id: str) -> str:
        self._output_path.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        # Trigger imports to register all collectors
        try:
            import collectors.marketplace.rss_collector  # noqa
            import collectors.marketplace.ouedkniss_collector  # noqa
            import collectors.marketplace.algeria_jobs_collector  # noqa
            import collectors.marketplace.algeria_forum_collector  # noqa
            import collectors.marketplace.algeria_gov_collector  # noqa
        except ImportError:
            pass

        from collectors.marketplace.base import CollectorRegistry

        registry_stats = CollectorRegistry.get_stats()
        all_collectors = CollectorRegistry.list_all()

        # Get health data if available
        health_data = {}
        try:
            storage_cfg = self._config.get("storage", {})
            db_path = storage_cfg.get("path", "data/market_intel.db")
            from collectors.marketplace.health import CollectorHealthMonitor
            monitor = CollectorHealthMonitor(db_path)
            health_data = monitor.get_all_health()
            health_stats = monitor.get_stats()
        except Exception:
            health_stats = {"total_collectors_tracked": 0, "by_status": {}, "total_items_collected_all_time": 0}

        lines: list[str] = []
        lines.append(f"# Collector Registry Report — {date_str}")
        lines.append("")
        lines.append(f"_Generated: {now.isoformat()} | Run: `{run_id}`_")
        lines.append("")
        lines.append("> **Phase 10 — Collector Marketplace.**")
        lines.append("> Anyone can drop a new collector into the platform without modifying the core engine.")
        lines.append("> The platform evolves from a single application into an ecosystem.")
        lines.append("")

        # ─── Registry Summary ────────────────────────────────────────────
        lines.append("## Registry Summary")
        lines.append("")
        lines.append(f"- **Total collectors:** {registry_stats.get('total_collectors', 0)}")
        lines.append(f"- **Requires credentials:** {registry_stats.get('requires_credentials', 0)}")
        lines.append("")

        by_country = registry_stats.get("by_country", {})
        if by_country:
            lines.append("**By country:**")
            lines.append("")
            for country, count in sorted(by_country.items(), key=lambda x: -x[1]):
                lines.append(f"- {country}: {count}")
            lines.append("")

        by_category = registry_stats.get("by_category", {})
        if by_category:
            lines.append("**By category:**")
            lines.append("")
            for category, count in sorted(by_category.items(), key=lambda x: -x[1]):
                lines.append(f"- {category}: {count}")
            lines.append("")

        # ─── All Collectors Table ────────────────────────────────────────
        lines.append(f"## All Registered Collectors ({len(all_collectors)})")
        lines.append("")
        if all_collectors:
            lines.append("| Name | Country | Category | Entity Types | Reliability | Rate Limit | Cost | Credentials | Health |")
            lines.append("|------|---------|----------|--------------|-------------|------------|------|-------------|--------|")
            for m in all_collectors:
                entity_types = ", ".join(m.entity_types[:3])
                if len(m.entity_types) > 3:
                    entity_types += f" +{len(m.entity_types) - 3}"
                credentials = ", ".join(m.required_credentials) if m.required_credentials else "—"
                health = health_data.get(m.name)
                health_status = health.status if health else "unknown"
                lines.append(
                    f"| `{m.name}` | {m.country} | {m.category} | {entity_types} | "
                    f"{m.reliability:.2f} | {m.rate_limit_per_hour}/h | "
                    f"{m.cost_per_call:.2f} | {credentials} | {health_status} |"
                )
            lines.append("")

        # ─── Collectors by Country (Algeria focus) ───────────────────────
        algeria_collectors = CollectorRegistry.list_by_country("DZ")
        lines.append(f"## Algerian Collectors ({len(algeria_collectors)})")
        lines.append("")
        if algeria_collectors:
            lines.append("> Algeria-first strategy — these collectors provide proprietary regional intelligence.")
            lines.append("")
            for m in algeria_collectors:
                lines.append(f"### {m.name}")
                lines.append(f"- **Category:** {m.category}")
                lines.append(f"- **Entity types:** {', '.join(m.entity_types)}")
                lines.append(f"- **Reliability:** {m.reliability:.2f}")
                lines.append(f"- **Rate limit:** {m.rate_limit_per_hour}/hour")
                lines.append(f"- **Description:** {m.description}")
                if m.required_credentials:
                    lines.append(f"- **Required credentials:** {', '.join(m.required_credentials)}")
                lines.append("")
        else:
            lines.append("_No Algerian collectors registered yet._")
            lines.append("")

        # ─── Collectors by Category ──────────────────────────────────────
        categories_present = set(m.category for m in all_collectors)
        lines.append("## Collectors by Category")
        lines.append("")
        for category in sorted(categories_present):
            cat_collectors = CollectorRegistry.list_by_category(category)
            lines.append(f"### {category.title()} ({len(cat_collectors)})")
            lines.append("")
            for m in cat_collectors:
                lines.append(f"- `{m.name}` ({m.country}) — {m.description}")
            lines.append("")

        # ─── Health Summary ──────────────────────────────────────────────
        lines.append("## Health Summary")
        lines.append("")
        if health_data:
            by_status = Counter(h.status for h in health_data.values())
            lines.append(f"- **Total collectors tracked:** {health_stats.get('total_collectors_tracked', 0)}")
            lines.append(f"- **Total items collected (all time):** {health_stats.get('total_items_collected_all_time', 0):,}")
            lines.append(f"- **Avg success rate:** {health_stats.get('avg_success_rate', 0):.1%}")
            lines.append("")
            lines.append("**By status:**")
            for status, count in by_status.most_common():
                lines.append(f"- {status}: {count}")
            lines.append("")

            # Detailed health table
            lines.append("### Per-Collector Health")
            lines.append("")
            lines.append("| Collector | Status | Success Rate | Total Calls | Items Collected | Avg Latency | Last Success | Last Error |")
            lines.append("|-----------|--------|--------------|--------------|-----------------|-------------|--------------|------------|")
            for name, h in sorted(health_data.items(), key=lambda x: x[1].success_rate, reverse=True):
                last_success = (h.last_success or "")[:10]
                last_error = (h.last_error or "")[:40] if h.last_error else "—"
                lines.append(
                    f"| `{name}` | {h.status} | {h.success_rate:.1%} | {h.total_calls} | "
                    f"{h.total_items_collected:,} | {h.avg_latency_ms:.0f}ms | "
                    f"{last_success} | {last_error} |"
                )
            lines.append("")
        else:
            lines.append("_No health data yet — collectors haven't been invoked._")
            lines.append("")

        # ─── How to Add a New Collector ──────────────────────────────────
        lines.append("## How to Add a New Collector")
        lines.append("")
        lines.append("```python")
        lines.append("from collectors.marketplace.base import MarketplaceCollector, CollectorMetadata")
        lines.append("from core.models import RawItem")
        lines.append("")
        lines.append("class MyCollector(MarketplaceCollector):")
        lines.append("    metadata = CollectorMetadata(")
        lines.append("        name='my_source',")
        lines.append("        country='DZ',                # ISO code")
        lines.append("        category='classifieds',      # news, classifieds, jobs, forum, government, social")
        lines.append("        entity_types=['product'],    # what entities this produces")
        lines.append("        description='My custom data source',")
        lines.append("        rate_limit_per_hour=60,")
        lines.append("        reliability=0.75,            # 0-1, used by TrustLayer")
        lines.append("        cost_per_call=0.0,")
        lines.append("        required_credentials=['MY_API_KEY'],  # env var names")
        lines.append("        tags=['algeria', 'custom'],")
        lines.append("    )")
        lines.append("")
        lines.append("    def collect(self) -> list[RawItem]:")
        lines.append("        # Your collection logic here")
        lines.append("        return [RawItem.create(")
        lines.append("            source='my_source',")
        lines.append("            source_name='My Source',")
        lines.append("            title='...',")
        lines.append("            url='...',")
        lines.append("            body='...',")
        lines.append("        )]")
        lines.append("")
        lines.append("# Register it")
        lines.append("from collectors.marketplace.base import CollectorRegistry")
        lines.append("CollectorRegistry.register(MyCollector())")
        lines.append("```")
        lines.append("")
        lines.append("The collector will then be:")
        lines.append("- Discoverable via `CollectorRegistry.list_by_country/category/entity_type`")
        lines.append("- Health-monitored by `CollectorHealthMonitor`")
        lines.append("- Trust-weighted by `TrustLayer` (using `metadata.reliability`)")
        lines.append("- Listed in this report automatically")
        lines.append("")

        # ─── Closed-loop status ──────────────────────────────────────────
        lines.append("## Closed-Loop Status")
        lines.append("")
        loop_steps = [
            ("Collect", "✅" if all_collectors else "⏸"),
            ("Marketplace", "✅" if all_collectors else "⏸"),
            ("Health Monitor", "✅" if health_data else "⏸"),
        ]
        for step, status in loop_steps:
            lines.append(f"- {status} **{step}**")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("_Market-Intel — Phase 10 Collector Marketplace._")
        lines.append("_Software is no longer the bottleneck. Competitive advantage comes from proprietary data coverage._")

        filepath = self._output_path / f"collector_registry_{date_str}_{run_id}.md"
        filepath.write_text("\n".join(lines), encoding="utf-8")

        self._logger.info(f"Collector registry report written to {filepath} ({len(all_collectors)} collectors)")
        return str(filepath)
