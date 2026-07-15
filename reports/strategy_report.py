"""
Strategy Report — Phase 5 markdown report.

Outputs the OPTIMAL PLAN under resource constraints:
  - Resource constraints (budget USD + time hours)
  - Selected actions (ordered by ROI efficiency)
  - Excluded actions (with reason)
  - Projected outcomes (signups, conversions, revenue, total ROI)
  - Budget allocation breakdown
  - Time allocation breakdown
  - Closed-loop status with strategy stage

Output: reports/strategy_<YYYY-MM-DD>_<run_id>.md
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from core.models import ProcessedItem
from core.logger import get_logger
from reports.base import BaseReportGenerator


class StrategyReportGenerator(BaseReportGenerator):
    name = "strategy"

    def __init__(self, config: dict):
        super().__init__(config)
        self._output_path = Path(config.get("output_path", "reports/"))

    def _generate(self, items: list[ProcessedItem], run_id: str) -> str:
        self._output_path.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        # Find strategy data
        strategy_data = None
        decisions_data = None
        for item in items:
            if strategy_data is None and "_strategy" in item.metadata:
                strategy_data = item.metadata["_strategy"]
            if decisions_data is None and "_decisions" in item.metadata:
                decisions_data = item.metadata["_decisions"]
            if strategy_data and decisions_data:
                break

        lines: list[str] = []
        lines.append(f"# Strategy Report — {date_str}")
        lines.append("")
        lines.append(f"_Generated: {now.isoformat()} | Run: `{run_id}`_")
        lines.append("")
        lines.append("> **This is the optimal plan under your resource constraints.**")
        lines.append("> Ranked by ROI per resource unit. Selected actions maximize projected outcomes within budget + time.")
        lines.append("")

        if not strategy_data:
            lines.append("_No strategy data available — Strategy Engine did not run._")
            lines.append("")
            filepath = self._output_path / f"strategy_{date_str}_{run_id}.md"
            filepath.write_text("\n".join(lines), encoding="utf-8")
            return str(filepath)

        constraints = strategy_data.get("constraints", {})
        selected = strategy_data.get("selected", [])
        excluded = strategy_data.get("excluded", [])
        projected = strategy_data.get("projected", {})
        utilization = strategy_data.get("utilization", {})

        # ─── Constraints ─────────────────────────────────────────────────
        lines.append("## Resource Constraints")
        lines.append("")
        lines.append(f"| Resource | Available | Used | Utilization |")
        lines.append(f"|----------|-----------|------|-------------|")
        lines.append(
            f"| **Budget** | ${constraints.get('budget_usd', 0):,} | "
            f"${utilization.get('budget_used_usd', 0):,} | "
            f"{utilization.get('budget_used_pct', 0):.1f}% |"
        )
        lines.append(
            f"| **Time** | {constraints.get('time_hours', 0) * constraints.get('team_size', 1)}h | "
            f"{utilization.get('time_used_hours', 0)}h | "
            f"{utilization.get('time_used_pct', 0):.1f}% |"
        )
        lines.append(f"| **Team size** | {constraints.get('team_size', 1)} | — | — |")
        lines.append("")

        # ─── Projected outcomes ──────────────────────────────────────────
        lines.append("## Projected Outcomes")
        lines.append("")
        lines.append(f"| Metric | Projected |")
        lines.append(f"|--------|-----------|")
        lines.append(f"| **Total ROI** | {projected.get('total_roi', 0):.1f} / 100 |")
        lines.append(f"| **Avg ROI per action** | {projected.get('avg_roi_per_selected', 0):.1f} |")
        lines.append(f"| **Projected signups** | {projected.get('total_signups', 0):,} |")
        lines.append(f"| **Projected conversions** | {projected.get('total_conversions', 0):,} |")
        lines.append(f"| **Projected revenue** | ${projected.get('total_revenue_usd', 0):,} |")
        lines.append("")

        # ─── Selected actions ────────────────────────────────────────────
        lines.append("## Optimal Plan — Selected Actions")
        lines.append("")
        lines.append(f"_{len(selected)} of {len(selected) + len(excluded)} candidate actions selected._")
        lines.append("")

        if selected:
            lines.append("| # | ROI | Type | Target | Cost (USD) | Time (h) | Signups | Revenue | Cumulative $ | Cumulative h |")
            lines.append("|---|-----|------|--------|-----------|----------|---------|---------|--------------|--------------|")
            for i, s in enumerate(selected, 1):
                d = s["decision"]
                lines.append(
                    f"| {i} | **{s['roi']:.1f}** | {d.get('type', '').replace('_', ' ')} | "
                    f"{d.get('target', '')} | ${s['cost_usd']:,} | {s['cost_hours']}h | "
                    f"{s['projected_signups']} | ${s['projected_revenue']:,} | "
                    f"${s['cumulative_budget']:,} | {s['cumulative_hours']}h |"
                )
            lines.append("")

            # Detailed rationale for each selected action
            lines.append("### Action Details")
            lines.append("")
            for i, s in enumerate(selected, 1):
                d = s["decision"]
                lines.append(f"#### {i}. [{d.get('priority', 'P3')}] {d.get('type', '').replace('_', ' ').title()} — {d.get('target', '')}")
                lines.append("")
                lines.append(f"- **ROI:** {s['roi']:.1f} / 100  (efficiency: {s['efficiency']})")
                lines.append(f"- **Cost:** ${s['cost_usd']:,} + {s['cost_hours']}h")
                lines.append(f"- **Projected:** {s['projected_signups']} signups, ${s['projected_revenue']:,} revenue")
                lines.append(f"- **Suggested action:** {d.get('suggested_action', '')}")
                lines.append(f"- **Rationale:** {d.get('rationale', '')}")
                lines.append("")

        # ─── Excluded actions ────────────────────────────────────────────
        if excluded:
            lines.append("## Excluded Actions (Did Not Fit Constraints)")
            lines.append("")
            lines.append("| ROI | Type | Target | Cost (USD) | Time (h) | Reason |")
            lines.append("|-----|------|--------|-----------|----------|--------|")
            for e in excluded:
                d = e["decision"]
                lines.append(
                    f"| {e['roi']:.1f} | {d.get('type', '').replace('_', ' ')} | "
                    f"{d.get('target', '')} | ${e['cost_usd']:,} | {e['cost_hours']}h | "
                    f"{e['reason']} |"
                )
            lines.append("")

        # ─── Budget allocation breakdown ─────────────────────────────────
        if selected:
            by_type: dict[str, dict] = {}
            for s in selected:
                dtype = s["decision"].get("type", "unknown")
                if dtype not in by_type:
                    by_type[dtype] = {"count": 0, "usd": 0, "hours": 0, "roi": 0}
                by_type[dtype]["count"] += 1
                by_type[dtype]["usd"] += s["cost_usd"]
                by_type[dtype]["hours"] += s["cost_hours"]
                by_type[dtype]["roi"] += s["roi"]

            lines.append("## Budget Allocation by Action Type")
            lines.append("")
            lines.append("| Type | Count | USD | % of Budget | Hours | % of Time | Total ROI |")
            lines.append("|------|-------|-----|-------------|-------|-----------|-----------|")
            for dtype, data in sorted(by_type.items(), key=lambda x: -x[1]["usd"]):
                budget_pct = (data["usd"] / max(1, constraints.get("budget_usd", 1))) * 100
                time_pct = (data["hours"] / max(1, constraints.get("time_hours", 1) * constraints.get("team_size", 1))) * 100
                lines.append(
                    f"| {dtype.replace('_', ' ')} | {data['count']} | ${data['usd']:,} | "
                    f"{budget_pct:.1f}% | {data['hours']}h | {time_pct:.1f}% | {data['roi']:.1f} |"
                )
            lines.append("")

        # ─── Filtered decisions summary ──────────────────────────────────
        if decisions_data and decisions_data.get("filter_counts"):
            fc = decisions_data["filter_counts"]
            lines.append("## Data Quality — False Positives Filtered")
            lines.append("")
            lines.append(f"_{sum(fc.values())} decisions filtered before strategy optimization._")
            lines.append("")
            lines.append("| Filter | Count |")
            lines.append("|--------|-------|")
            for reason, count in sorted(fc.items(), key=lambda x: -x[1]):
                lines.append(f"| `{reason}` | {count} |")
            lines.append("")

        # ─── Strategy recommendation ─────────────────────────────────────
        lines.append("## Strategic Recommendation")
        lines.append("")
        if selected:
            top = selected[0]
            lines.append(f"**Lead with:** {top['decision'].get('type', '').replace('_', ' ').title()} targeting **{top['decision'].get('target', '')}** (ROI {top['roi']:.1f}).")
            lines.append("")
            lines.append(f"**Why:** {top['decision'].get('rationale', '')}")
            lines.append("")
            lines.append(f"**Total investment:** ${utilization.get('budget_used_usd', 0):,} + {utilization.get('time_used_hours', 0)}h")
            lines.append(f"**Projected return:** {projected.get('total_signups', 0)} signups, ${projected.get('total_revenue_usd', 0):,} revenue")
            lines.append("")

            # Slack / overage note
            slack_budget = constraints.get("budget_usd", 0) - utilization.get("budget_used_usd", 0)
            slack_time = constraints.get("time_hours", 0) * constraints.get("team_size", 1) - utilization.get("time_used_hours", 0)
            if slack_budget > 0 or slack_time > 0:
                lines.append(f"**Slack remaining:** ${slack_budget:,} + {slack_time}h — consider raising budget/time constraints or pulling in next-best action from excluded list.")
            else:
                lines.append("**Fully allocated** — no slack remaining. Increase budget or time to unlock more actions.")
            lines.append("")

        # ─── Closed-loop status ──────────────────────────────────────────
        lines.append("## Closed-Loop Status")
        lines.append("")
        loop_steps = [
            ("Collect", "✅"),
            ("Analyze", "✅"),
            ("Score", "✅"),
            ("Decide", "✅" if decisions_data else "⏸"),
            ("Filter", "✅" if decisions_data and decisions_data.get("filter_counts") else "⏸"),
            ("Strategize", "✅" if strategy_data else "⏸"),
            ("Act", "✅"),
            ("Measure", "✅"),
            ("Learn", "✅"),
        ]
        for step, status in loop_steps:
            lines.append(f"- {status} **{step}**")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("_Market-Intel autonomous growth platform — Phase 5 (Strategy Engine)._")

        filepath = self._output_path / f"strategy_{date_str}_{run_id}.md"
        filepath.write_text("\n".join(lines), encoding="utf-8")

        self._logger.info(f"Strategy report written to {filepath}")
        return str(filepath)
