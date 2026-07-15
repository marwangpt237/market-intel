"""
Decision Report — Phase 4 markdown report.

Lists:
  1. Top decisions (priority-ordered) with rationale + suggested action
  2. Executed artifacts (paths to generated markdown files)
  3. Analytics summary (actions by status + aggregate metrics)
  4. Learning adjustments (thresholds that shifted this cycle)
  5. Closed-loop status (collect → analyze → score → decide → act → measure → learn)

Output: reports/decisions_<YYYY-MM-DD>_<run_id>.md
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from core.models import ProcessedItem
from core.logger import get_logger
from reports.base import BaseReportGenerator


class DecisionReportGenerator(BaseReportGenerator):
    name = "decisions"

    def __init__(self, config: dict):
        super().__init__(config)
        self._output_path = Path(config.get("output_path", "reports/"))
        self._top_n = int(config.get("top_decisions_count", 15))

    def _generate(self, items: list[ProcessedItem], run_id: str) -> str:
        self._output_path.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        # Pull Phase 4 metadata
        decisions_data = None
        executions_data = None
        analytics_data = None
        learning_data = None
        scores_data = None
        for item in items:
            if decisions_data is None and "_decisions" in item.metadata:
                decisions_data = item.metadata["_decisions"]
            if executions_data is None and "_executions" in item.metadata:
                executions_data = item.metadata["_executions"]
            if analytics_data is None and "_analytics" in item.metadata:
                analytics_data = item.metadata["_analytics"]
            if learning_data is None and "_learning" in item.metadata:
                learning_data = item.metadata["_learning"]
            if scores_data is None and "_scores" in item.metadata:
                scores_data = item.metadata["_scores"]
            if all([decisions_data, executions_data, analytics_data, learning_data, scores_data]):
                break

        lines: list[str] = []
        lines.append(f"# Decision Report — {date_str}")
        lines.append("")
        lines.append(f"_Generated: {now.isoformat()} | Run: `{run_id}`_")
        lines.append("")
        lines.append("> This is the closed-loop output of the Market-Intel platform.")
        lines.append("> Score → Decide → Act → Measure → Learn. Adjustments below feed into the next run.")
        lines.append("")

        # ─── Decision summary header ─────────────────────────────────────
        if decisions_data:
            by_p = decisions_data.get("by_priority", {})
            by_t = decisions_data.get("by_type", {})
            total = decisions_data.get("total", 0)
            lines.append("## Decision Summary")
            lines.append("")
            lines.append(f"**Total decisions: {total}**")
            lines.append("")
            lines.append("| Priority | Count |")
            lines.append("|----------|-------|")
            for p in ("P0", "P1", "P2", "P3"):
                lines.append(f"| {p} | {by_p.get(p, 0)} |")
            lines.append("")
            lines.append("**By type:**")
            for dtype, count in sorted(by_t.items(), key=lambda x: -x[1]):
                lines.append(f"- `{dtype}`: {count}")
            lines.append("")

        # ─── Top decisions ────────────────────────────────────────────────
        if decisions_data and decisions_data.get("decisions"):
            lines.append("## Top Decisions (priority-ordered)")
            lines.append("")
            for i, d in enumerate(decisions_data["decisions"][: self._top_n], 1):
                lines.append(f"### {i}. [{d['priority']}] {d['type'].replace('_', ' ').title()} — {d['target']}")
                lines.append("")
                lines.append(f"**Suggested action:** {d.get('suggested_action', '')}")
                lines.append("")
                lines.append(f"**Rationale:** {d.get('rationale', '')}")
                lines.append("")
                meta_bits = [f"Expected impact: **{d.get('expected_impact', 'medium')}**"]
                if d.get("urgency_hours"):
                    meta_bits.append(f"Urgency: within {d['urgency_hours'] // 24} days")
                meta_bits.append(f"Decision ID: `{d['id']}`")
                lines.append(" · ".join(meta_bits))
                lines.append("")

                evidence = d.get("evidence", [])
                if evidence:
                    lines.append("**Evidence:**")
                    for e in evidence[:3]:
                        lines.append(f"- [{e.get('title', 'Untitled')}]({e.get('url', '')}) — _{e.get('source', '')}_")
                    if len(evidence) > 3:
                        lines.append(f"- _+ {len(evidence) - 3} more_")
                    lines.append("")

        # ─── Executed artifacts ──────────────────────────────────────────
        if executions_data:
            lines.append("## Executed Artifacts")
            lines.append("")
            lines.append(f"_{executions_data.get('total', 0)} markdown files generated in `{executions_data.get('output_dir', '')}`_")
            lines.append("")
            artifacts = executions_data.get("artifacts", [])
            if artifacts:
                lines.append("| Decision ID | Type | Format | Path |")
                lines.append("|-------------|------|--------|------|")
                for a in artifacts:
                    short_id = a.get("decision_id", "")[:20]
                    path = a.get("path", "")
                    # Make path relative if possible
                    if path:
                        path = path.replace("/home/z/my-project/repos/market-intel/", "")
                    lines.append(
                        f"| `{short_id}` | {a.get('type', '')} | {a.get('format', '')} | `{path}` |"
                    )
                lines.append("")
                lines.append("> Review each artifact. Send/publish manually. Update `data/metrics_input_template.json` with outcomes.")
                lines.append("")

        # ─── Analytics summary ───────────────────────────────────────────
        if analytics_data:
            lines.append("## Analytics Summary")
            lines.append("")
            lines.append(f"- **New actions recorded this run:** {analytics_data.get('actions_recorded_this_run', 0)}")
            lines.append(f"- **Total actions in DB:** {analytics_data.get('total_actions_in_db', 0)}")
            by_status = analytics_data.get("actions_by_status", {})
            if by_status:
                lines.append(f"- **By status:** {', '.join(f'{k}={v}' for k, v in by_status.items())}")
            by_type = analytics_data.get("actions_by_type", {})
            if by_type:
                lines.append(f"- **By type:** {', '.join(f'{k}={v}' for k, v in by_type.items())}")
            lines.append(f"- **Metrics input template:** `{analytics_data.get('metrics_input_path', '').replace('/home/z/my-project/repos/market-intel/', '')}`")
            lines.append("")

        # ─── Learning adjustments ────────────────────────────────────────
        if learning_data:
            lines.append("## Learning Engine — Weight Adjustments")
            lines.append("")
            adjustments = learning_data.get("weight_adjustments", [])
            data_points = learning_data.get("data_points", 0)
            lines.append(f"_Analyzed {data_points} action buckets against baseline._")
            lines.append("")
            if not adjustments:
                lines.append("No threshold adjustments this cycle (either insufficient data or all buckets within ±20% of baseline).")
                lines.append("")
            else:
                lines.append("| Decision Type | Priority | Threshold | Old | New | Δ Outcome vs Baseline | Sample |")
                lines.append("|---------------|----------|-----------|-----|-----|------------------------|--------|")
                for adj in adjustments:
                    lines.append(
                        f"| {adj['decision_type']} | {adj['priority']} | `{adj['threshold']}` | "
                        f"{adj['old_value']} | {adj['new_value']} | "
                        f"{adj['delta_pct']:+.0%} (avg {adj['avg_outcome']} vs baseline {adj['baseline_outcome']}) | "
                        f"{adj['sample_size']} |"
                    )
                lines.append("")
                lines.append(f"_New weights persisted to `{learning_data.get('weights_path', '').replace('/home/z/my-project/repos/market-intel/', '')}`._")
                lines.append("_Next run's scoring + decision engines will load these adjusted thresholds._")
                lines.append("")

        # ─── Closed-loop status ──────────────────────────────────────────
        lines.append("## Closed-Loop Status")
        lines.append("")
        loop_steps = [
            ("Collect", "✅", "Items collected + deduped"),
            ("Analyze", "✅", "Entities + competitors + pain points + signals extracted"),
            ("Score", "✅", "Opportunity / threat / trend / competitor weakness scores computed"),
            ("Decide", "✅" if decisions_data else "⏸", f"{decisions_data.get('total', 0) if decisions_data else 0} decisions ranked by priority"),
            ("Act", "✅" if executions_data else "⏸", f"{executions_data.get('total', 0) if executions_data else 0} artifacts generated"),
            ("Measure", "✅" if analytics_data else "⏸", f"{analytics_data.get('total_actions_in_db', 0) if analytics_data else 0} actions tracked in SQLite"),
            ("Learn", "✅" if learning_data else "⏸", f"{len(learning_data.get('weight_adjustments', [])) if learning_data else 0} weight adjustments"),
        ]
        for step, status, detail in loop_steps:
            lines.append(f"- {status} **{step}** — {detail}")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("_Market-Intel autonomous growth platform — Phase 4._")

        # Write report
        filename = f"decisions_{date_str}_{run_id}.md"
        filepath = self._output_path / filename
        filepath.write_text("\n".join(lines), encoding="utf-8")

        self._logger.info(f"Decision report written to {filepath}")
        return str(filepath)
