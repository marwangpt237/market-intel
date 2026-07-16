"""
Acquisition Report — Phase 9 markdown report.

Reports on the autonomous research planner:
  1. Executive Summary (total gaps, total plans, projected confidence lift)
  2. Top Priority Plans (P0 + P1, with concrete actions)
  3. Knowledge Gaps by Category
  4. Scheduled Collections (frequency increases, historical pulls)
  5. Next Validation Cycle (when to re-run validation)
  6. Cost Estimate (resource cost of executing all plans)
  7. Closed-loop status

Output: reports/acquisition_<YYYY-MM-DD>_<run_id>.md
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from core.models import ProcessedItem
from core.logger import get_logger
from reports.base import BaseReportGenerator


class AcquisitionReportGenerator(BaseReportGenerator):
    name = "acquisition"

    def __init__(self, config: dict):
        super().__init__(config)
        self._output_path = Path(config.get("output_path", "reports/"))
        self._top_plans = int(config.get("top_plans_count", 15))

    def _generate(self, items: list[ProcessedItem], run_id: str) -> str:
        self._output_path.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        acquisition_data = None
        for item in items:
            if "_acquisition" in item.metadata:
                acquisition_data = item.metadata["_acquisition"]
                break

        lines: list[str] = []
        lines.append(f"# Data Acquisition Report — {date_str}")
        lines.append("")
        lines.append(f"_Generated: {now.isoformat()} | Run: `{run_id}`_")
        lines.append("")
        lines.append("> **Phase 9 — Autonomous Research Planner.**")
        lines.append("> Instead of passively reporting missing evidence, the system actively plans how to obtain it.")
        lines.append("> The platform is now a self-improving research system whose limiting factor is access to real-world data.")
        lines.append("")

        if not acquisition_data:
            lines.append("_No acquisition data available — Data Acquisition Planner did not run._")
            filepath = self._output_path / f"acquisition_{date_str}_{run_id}.md"
            filepath.write_text("\n".join(lines), encoding="utf-8")
            return str(filepath)

        gaps = acquisition_data.get("gaps", [])
        plans = acquisition_data.get("plans", [])
        summary = acquisition_data.get("summary", {})

        # ─── Executive Summary ───────────────────────────────────────────
        lines.append("## Executive Summary")
        lines.append("")
        lines.append(f"- **Knowledge gaps detected:** {len(gaps)}")
        lines.append(f"- **Collection plans generated:** {len(plans)}")
        lines.append(f"- **Estimated new evidence:** {summary.get('total_estimated_evidence', 0)} pieces")
        lines.append(f"- **Estimated confidence lift:** +{summary.get('total_confidence_lift', 0):.2f}")
        lines.append(f"- **Total resource cost:** {summary.get('total_cost', 0):.1f} units")
        lines.append(f"- **Next validation cycle:** in {summary.get('next_validation_hours', 24)}h")
        lines.append("")

        # Gap priority distribution
        gap_priority_counts = Counter(g.get("priority", "P3") for g in gaps)
        if gap_priority_counts:
            lines.append("**Gaps by priority:**")
            lines.append("")
            for p in ("P0", "P1", "P2", "P3"):
                count = gap_priority_counts.get(p, 0)
                if count > 0:
                    lines.append(f"- {p}: {count} gaps")
            lines.append("")

        # ─── Top Priority Plans ──────────────────────────────────────────
        lines.append(f"## Top Priority Plans ({min(len(plans), self._top_plans)})")
        lines.append("")
        if plans:
            lines.append("> Each plan addresses a knowledge gap with concrete collection actions.")
            lines.append("")

            for i, plan in enumerate(plans[: self._top_plans], 1):
                lines.append(f"### {i}. [{plan['priority']}] {plan['entity_name']} — {plan['gap_type'].replace('_', ' ').title()}")
                lines.append("")
                lines.append(f"- **Plan ID:** `{plan.get('plan_id', '?')[:12]}`")
                lines.append(f"- **Gap addressed:** `{plan.get('gap_id', '?')[:12]}`")
                lines.append(f"- **Current confidence:** {plan['current_confidence']:.2f} → **Target:** {plan['target_confidence']:.2f} (Δ +{plan['estimated_confidence_lift']:.2f})")
                lines.append(f"- **Estimated new evidence:** {plan['estimated_evidence_gain']} pieces")
                lines.append(f"- **Resource cost:** {plan['total_cost']:.1f} units")
                lines.append(f"- **Next validation:** in {plan['next_validation_hours']}h")
                lines.append("")

                if plan.get("actions"):
                    lines.append("**Actions:**")
                    lines.append("")
                    for j, action in enumerate(plan["actions"], 1):
                        action_str = self._format_action(action)
                        lines.append(f"{j}. {action_str}")
                    lines.append("")
        else:
            lines.append("_No collection plans generated — no knowledge gaps detected._")
            lines.append("")

        # ─── Knowledge Gaps by Category ──────────────────────────────────
        lines.append("## Knowledge Gaps by Category")
        lines.append("")
        gap_type_counts: Counter = Counter(g.get("gap_type", "unknown") for g in gaps)
        if gap_type_counts:
            lines.append("| Gap Type | Count | Avg Confidence | Suggested Sources |")
            lines.append("|----------|-------|---------------|-------------------|")
            # Compute avg confidence per gap type
            gap_type_confidences: dict[str, list[float]] = {}
            for g in gaps:
                gt = g.get("gap_type", "unknown")
                if gt not in gap_type_confidences:
                    gap_type_confidences[gt] = []
                gap_type_confidences[gt].append(g.get("current_confidence", 0))

            for gap_type, count in gap_type_counts.most_common():
                confidences = gap_type_confidences.get(gap_type, [0])
                avg_conf = sum(confidences) / len(confidences) if confidences else 0
                # Get suggested sources from first gap of this type
                first_gap = next((g for g in gaps if g.get("gap_type") == gap_type), {})
                sources = ", ".join(first_gap.get("suggested_source_types", [])[:3])
                lines.append(
                    f"| {gap_type.replace('_', ' ').title()} | {count} | "
                    f"{avg_conf:.2f} | {sources} |"
                )
            lines.append("")
        else:
            lines.append("_No knowledge gaps detected this run._")
            lines.append("")

        # ─── Scheduled Collections ───────────────────────────────────────
        scheduled_actions = []
        for plan in plans:
            for action in plan.get("actions", []):
                if action.get("action_type") in ("increase_frequency", "historical_collection", "schedule_validation"):
                    scheduled_actions.append({**action, "plan_id": plan.get("plan_id", ""), "entity": plan.get("entity_name", "")})

        lines.append(f"## Scheduled Collections ({len(scheduled_actions)})")
        lines.append("")
        if scheduled_actions:
            lines.append("| Action Type | Entity | Source | Frequency | Quantity | Next Validation |")
            lines.append("|-------------|--------|--------|-----------|----------|-----------------|")
            for action in scheduled_actions[:20]:
                lines.append(
                    f"| {action.get('action_type', '').replace('_', ' ').title()} | "
                    f"{action.get('entity', '')[:20]} | "
                    f"{action.get('source_type', '')} | "
                    f"{action.get('frequency_hours', 0)}h | "
                    f"{action.get('quantity', 0)} | "
                    f"{action.get('next_validation_hours', 0)}h |"
                )
            lines.append("")
        else:
            lines.append("_No scheduled collections this run._")
            lines.append("")

        # ─── Next Validation Cycle ───────────────────────────────────────
        lines.append("## Next Validation Cycle")
        lines.append("")
        next_validation = summary.get("next_validation_hours", 24)
        lines.append(f"**Re-run validation in {next_validation} hours** to check if collection plans succeeded.")
        lines.append("")
        lines.append("The closed loop:")
        lines.append("")
        lines.append("```")
        lines.append("Collect → Analyze → Validate → Detect Knowledge Gaps →")
        lines.append("Plan Data Acquisition → Collect Missing Evidence →")
        lines.append("Revalidate → Update Knowledge Graph →")
        lines.append("Generate Decisions → Measure Outcomes → Learn")
        lines.append("```")
        lines.append("")

        # ─── Cost Estimate ───────────────────────────────────────────────
        lines.append("## Resource Cost Estimate")
        lines.append("")
        lines.append(f"- **Total cost:** {summary.get('total_cost', 0):.1f} units")
        lines.append(f"- **Estimated evidence gain:** {summary.get('total_estimated_evidence', 0)} pieces")
        lines.append(f"- **Cost per evidence piece:** {summary.get('total_cost', 0) / max(1, summary.get('total_estimated_evidence', 1)):.2f} units")
        lines.append("")
        lines.append("> Cost units are relative (API calls + time). Use to prioritize which plans to execute first.")
        lines.append("")

        # ─── How it works ────────────────────────────────────────────────
        lines.append("## How the Planner Works")
        lines.append("")
        lines.append("```")
        lines.append("1. Knowledge Gap Detector aggregates missing-evidence requests from Validation Engine")
        lines.append("   - Groups by (entity, claim_type)")
        lines.append("   - Computes priority: P0 (high impact + urgent) → P3 (minimal)")
        lines.append("")
        lines.append("2. Data Acquisition Planner generates concrete actions per gap:")
        lines.append("   - crawl: collect N items from source X with query Y")
        lines.append("   - increase_frequency: collect every N hours instead of default")
        lines.append("   - historical_collection: pull N days of historical data")
        lines.append("   - search_corroboration: search additional sources for cross-validation")
        lines.append("   - schedule_validation: re-run Validation Engine in N hours")
        lines.append("")
        lines.append("3. Each plan estimates:")
        lines.append("   - evidence_gain (how many new evidence pieces expected)")
        lines.append("   - confidence_lift (how much target confidence will improve)")
        lines.append("   - cost (resource units: API calls + time)")
        lines.append("```")
        lines.append("")

        # ─── Closed-loop status ──────────────────────────────────────────
        lines.append("## Closed-Loop Status")
        lines.append("")
        loop_steps = [
            ("Collect", "✅"),
            ("Analyze", "✅"),
            ("Validate", "✅"),
            ("Detect Gaps", "✅" if gaps else "⏸"),
            ("Plan Acquisition", "✅" if plans else "⏸"),
            ("Collect Missing", "⏸"),  # next run
            ("Revalidate", "⏸"),       # scheduled
            ("Update Knowledge", "⏸"),
            ("Generate Decisions", "✅"),
            ("Measure Outcomes", "✅"),
            ("Learn", "✅"),
        ]
        for step, status in loop_steps:
            lines.append(f"- {status} **{step}**")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("_Market-Intel — Phase 9 Autonomous Research Planner._")
        lines.append("_The platform's limiting factor is now access to real-world data, not software architecture._")

        filepath = self._output_path / f"acquisition_{date_str}_{run_id}.md"
        filepath.write_text("\n".join(lines), encoding="utf-8")

        self._logger.info(f"Acquisition report written to {filepath} ({len(plans)} plans)")
        return str(filepath)

    @staticmethod
    def _format_action(action: dict) -> str:
        """Format an action dict as a human-readable string."""
        action_type = action.get("action_type", "unknown")
        source = action.get("source_type", "")
        query = action.get("query", "")
        quantity = action.get("quantity", 0)
        frequency = action.get("frequency_hours", 0)
        historical = action.get("historical_days", 0)
        evidence = action.get("estimated_evidence", 0)
        cost = action.get("estimated_cost", 0)
        next_val = action.get("next_validation_hours", 0)

        if action_type == "crawl":
            return f"**Crawl** {quantity} items from `{source}` — query: \"{query}\" (est. {evidence} evidence, cost {cost:.1f})"
        elif action_type == "search_corroboration":
            return f"**Search** {source} for corroboration — query: \"{query}\" (est. {evidence} evidence, cost {cost:.1f})"
        elif action_type == "historical_collection":
            return f"**Historical** collection: {historical} days from `{source}` — query: \"{query}\" (est. {evidence} evidence, cost {cost:.1f})"
        elif action_type == "increase_frequency":
            return f"**Increase frequency** of `{source}` to every {frequency}h — query: \"{query}\" (est. {evidence} evidence over 7 days, cost {cost:.1f})"
        elif action_type == "schedule_validation":
            return f"**Schedule validation** in {next_val}h to check if plans succeeded"
        else:
            return f"**{action_type}** — {source} ({quantity} items, cost {cost:.1f})"
