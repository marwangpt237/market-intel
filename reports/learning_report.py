"""
Learning Report — Phase 6 markdown report.

Shows the state of the learned model:
  - Model stats (total features, samples, MAE)
  - Top features by weight (most positive influence on outcome)
  - Bottom features by weight (most negative influence)
  - Features with biggest shift from baseline (most learned)
  - Cold-start status (which features are still on baseline)
  - Closed-loop status

Output: reports/learning_<YYYY-MM-DD>_<run_id>.md
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from core.models import ProcessedItem
from core.logger import get_logger
from reports.base import BaseReportGenerator


class LearningReportGenerator(BaseReportGenerator):
    name = "learning"

    def __init__(self, config: dict):
        super().__init__(config)
        self._output_path = Path(config.get("output_path", "reports/"))

    def _generate(self, items: list[ProcessedItem], run_id: str) -> str:
        self._output_path.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        # Find learning data
        learning_data = None
        for item in items:
            if "_learning" in item.metadata:
                learning_data = item.metadata["_learning"]
                break

        lines: list[str] = []
        lines.append(f"# Learning Report — {date_str}")
        lines.append("")
        lines.append(f"_Generated: {now.isoformat()} | Run: `{run_id}`_")
        lines.append("")
        lines.append("> **Phase 6: Feedback-driven scoring.**")
        lines.append("> Weights are no longer hand-tuned — they are learned from observed outcomes via online SGD.")
        lines.append("> Score = Σ(feature × learned_weight) + bias")
        lines.append("")

        if not learning_data:
            lines.append("_No learning data available — Learning Engine did not run._")
            filepath = self._output_path / f"learning_{date_str}_{run_id}.md"
            filepath.write_text("\n".join(lines), encoding="utf-8")
            return str(filepath)

        # ─── Bucket-level adjustments (Phase 4, still running) ───────────
        bucket_adjustments = learning_data.get("weight_adjustments", [])
        bucket_outcomes = learning_data.get("bucket_outcomes", [])
        metrics_synced = learning_data.get("metrics_synced", 0)

        lines.append("## Phase 4 — Bucket-Level Adjustments (Legacy)")
        lines.append("")
        lines.append(f"- **User metrics synced this run:** {metrics_synced}")
        lines.append(f"- **Bucket outcomes analyzed:** {len(bucket_outcomes)}")
        lines.append(f"- **Threshold adjustments:** {len(bucket_adjustments)}")
        lines.append("")

        if bucket_outcomes:
            lines.append("| Decision Type | Priority | Sample Size | Avg Outcome |")
            lines.append("|---------------|----------|-------------|-------------|")
            for b in bucket_outcomes:
                lines.append(
                    f"| {b.get('decision_type', '')} | {b.get('priority', '')} | "
                    f"{b.get('count', 0)} | {b.get('avg_outcome', 0):.2f} |"
                )
            lines.append("")

        # ─── Phase 6: Learned feature weights ────────────────────────────
        learned = learning_data.get("learned_feature_weights", {})
        lines.append("## Phase 6 — Learned Feature Weights")
        lines.append("")
        lines.append(f"_{learned.get('message', 'No data')}_")
        lines.append("")

        if "model_stats" in learned:
            stats = learned["model_stats"]
            lines.append("### Model Stats")
            lines.append("")
            lines.append(f"| Metric | Value |")
            lines.append(f"|--------|-------|")
            lines.append(f"| Total features | {stats.get('total_features', 0)} |")
            lines.append(f"| Features with samples | {stats.get('features_with_samples', 0)} |")
            lines.append(f"| Features with enough samples (≥{stats.get('cold_start_threshold', 5)}) | {stats.get('features_with_enough_samples', 0)} |")
            lines.append(f"| Total samples observed | {stats.get('total_samples', 0)} |")
            lines.append(f"| Bias term | {stats.get('bias', 0):.2f} |")
            lines.append(f"| Bias samples | {stats.get('bias_samples', 0)} |")
            lines.append(f"| Learning rate | {stats.get('learning_rate', 0.01)} |")
            lines.append(f"| L2 regularization | {stats.get('regularization', 0.001)} |")
            lines.append(f"| Cold-start threshold | {stats.get('cold_start_threshold', 5)} samples |")
            lines.append("")

            # MAE
            if "mean_absolute_error" in learned:
                lines.append(f"**Mean Absolute Error (prediction vs actual):** {learned['mean_absolute_error']}/100")
                lines.append(f"**Avg prediction error:** {learned.get('avg_prediction_error', 0):+.2f} (negative = under-predicting)")
                lines.append("")
                lines.append("> Lower MAE = better-calibrated model. Target: < 15/100 after 50+ samples per feature.")
                lines.append("")

            # Biggest shifts from baseline
            if stats.get("biggest_positive_shift"):
                ps = stats["biggest_positive_shift"]
                lines.append(f"**Biggest positive shift:** `{ps['feature']}` — {ps['baseline']:+.2f} → {ps['weight']:+.2f} (Δ {ps['delta']:+.2f})")
                lines.append("")
            if stats.get("biggest_negative_shift"):
                ns = stats["biggest_negative_shift"]
                lines.append(f"**Biggest negative shift:** `{ns['feature']}` — {ns['baseline']:+.2f} → {ns['weight']:+.2f} (Δ {ns['delta']:+.2f})")
                lines.append("")

        # ─── Feature importance table ────────────────────────────────────
        if "feature_importance" in learned and learned["feature_importance"]:
            lines.append("### Feature Importance (Top 10 by absolute weight)")
            lines.append("")
            lines.append("| Feature | Learned Weight | Baseline | Δ from Baseline | Samples | Status |")
            lines.append("|---------|----------------|----------|-----------------|---------|--------|")
            for fi in learned["feature_importance"]:
                cold_start_threshold = stats.get("cold_start_threshold", 5) if "model_stats" in learned and "stats" in locals() else 5
                status = "✅ learned" if fi["samples"] >= cold_start_threshold else f"❄️ cold-start ({fi['samples']}/{cold_start_threshold})"
                lines.append(
                    f"| `{fi['feature']}` | {fi['weight']:+.2f} | {fi['baseline']:+.2f} | "
                    f"{fi['delta_from_baseline']:+.2f} | {fi['samples']} | {status} |"
                )
            lines.append("")

        # ─── How it works ────────────────────────────────────────────────
        lines.append("## How the Learned Scorer Works")
        lines.append("")
        lines.append("```")
        lines.append("Cold start (samples < 5):")
        lines.append("  weight = baseline_weight (from BASELINE_WEIGHTS table)")
        lines.append("")
        lines.append("After 5+ samples:")
        lines.append("  weight learned via online SGD:")
        lines.append("    prediction = Σ(feature × weight) + bias")
        lines.append("    error = prediction - actual_outcome")
        lines.append("    gradient = error × feature_value + λ × weight")
        lines.append("    weight -= learning_rate × gradient")
        lines.append("")
        lines.append("Outcome normalization:")
        lines.append("  outcome = clicks×1 + signups×5 + conversions×25 + revenue×0.1")
        lines.append("  clamped to 0-100")
        lines.append("")
        lines.append("Strategy Engine blends:")
        lines.append("  <5 features with enough samples: 30% learned + 70% heuristic")
        lines.append("  ≥5 features with enough samples: 70% learned + 30% heuristic")
        lines.append("```")
        lines.append("")

        # ─── Closed-loop status ──────────────────────────────────────────
        lines.append("## Closed-Loop Status")
        lines.append("")
        loop_steps = [
            ("Collect", "✅"),
            ("Analyze", "✅"),
            ("Score", "✅"),
            ("Decide", "✅"),
            ("Filter", "✅"),
            ("Strategize", "✅"),
            ("Act", "✅"),
            ("Measure", "✅"),
            ("Learn (bucket)", "✅" if bucket_adjustments or bucket_outcomes else "⏸"),
            ("Learn (feature)", "✅" if learned.get("actions_updated", 0) > 0 else "⏸"),
        ]
        for step, status in loop_steps:
            lines.append(f"- {status} **{step}**")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("_Market-Intel autonomous growth platform — Phase 6 (Feedback-Driven Scoring)._")

        filepath = self._output_path / f"learning_{date_str}_{run_id}.md"
        filepath.write_text("\n".join(lines), encoding="utf-8")

        self._logger.info(f"Learning report written to {filepath}")
        return str(filepath)
