"""
Learning Engine — Phase 4 module.

Reads action outcomes from SQLite (`actions` table) and the user-filled
`metrics_input_template.json`, then adjusts scoring weights for the next run.

Closed loop:
  Run N:    Score → Decide → Execute → Record (status=draft)
  User:     Fills in metrics_input_template.json (clicks, signups, conversions, status)
  Run N+1:  Learning engine reads updated metrics → recomputes weights →
            writes `data/learning_weights.json` → Scoring & Decision engines
            load the new weights → better decisions next cycle.

Adjustment logic (deterministic, no ML):
  For each decision_type T (build_feature, launch_campaign, write_content, ...):
    - Bucket historical actions by priority (P0, P1, P2, P3)
    - Compute avg outcome score per bucket:
        outcome = signups * 1 + conversions * 5 + revenue / 10
    - Compare to baseline (overall avg outcome for that type)
    - If bucket outperforms baseline by > 20% → boost the threshold-lowering
      (i.e., make this priority/type easier to trigger)
    - If bucket underperforms by > 20% → raise threshold (make harder to trigger)

Weights file format (data/learning_weights.json):
  {
    "opportunity_high": 55,         # was 60, lowered because P0 build_feature performed well
    "opportunity_medium": 30,       # was 35, lowered because P1 launch_campaign performed well
    "trend_hot": 50,                # was 60, raised because hot topics underperformed
    "weight_adjustments": [
      {
        "decision_type": "build_feature",
        "priority": "P0",
        "avg_outcome": 12.5,
        "baseline_outcome": 6.8,
        "delta_pct": 0.84,
        "action": "lowered opportunity_high from 60 to 55"
      },
      ...
    ],
    "last_updated": "2026-07-15T...",
    "data_points": 42
  }

This is intentionally simple — no neural nets, no gradient descent. Just
moving thresholds based on observed outcomes. Robust, debuggable, auditable.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


# Default thresholds (must match decision_engine defaults)
_DEFAULT_THRESHOLDS = {
    "opportunity_high": 60,
    "opportunity_medium": 35,
    "threat_high": 60,
    "threat_medium": 35,
    "weakness_high": 50,
    "trend_hot": 60,
    "trend_rising": 35,
    "min_evidence": 2,
}

# How much a bucket must outperform / underperform baseline to trigger adjustment
_PERFORMANCE_DELTA = 0.20  # 20%
# Max adjustment per cycle (prevents wild swings)
_MAX_ADJUSTMENT = 10
# Outcome score formula weights
_OUTCOME_WEIGHTS = {"clicks": 1, "signups": 5, "conversions": 25, "revenue": 0.1}


class LearningEngine(BaseProcessor):
    name = "learning_engine"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        storage_cfg = self._config.get("storage", {})
        self._db_path = storage_cfg.get("path", "data/market_intel.db")
        self._weights_path = Path(self._db_path).parent / "learning_weights.json"
        self._metrics_input_path = Path(self._db_path).parent / "metrics_input_template.json"
        self._lock = threading.Lock()
        # Ensure schema exists (defensive — analytics_engine may not have run yet)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create actions table if it doesn't exist (idempotent)."""
        from processors.analytics_engine import _ACTIONS_SCHEMA
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.executescript(_ACTIONS_SCHEMA)
            conn.commit()
            conn.close()

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        if not items:
            return items

        # 1. Sync metrics from user-filled template into SQLite
        synced = self._sync_user_metrics()

        # 2. Load current weights (or defaults)
        current_weights = self._load_current_weights()

        # 3. Compute per-bucket outcomes
        bucket_outcomes = self._compute_bucket_outcomes()

        # 4. Generate adjustments
        adjustments, new_weights = self._compute_adjustments(current_weights, bucket_outcomes)

        # 5. Persist new weights
        self._save_weights(new_weights, adjustments, len(bucket_outcomes))

        # 5b. Phase 6: Update learned feature weights from observed outcomes
        learned_update = self._update_learned_feature_weights(items)

        # 6. Stash on first item
        items[0].metadata["_learning"] = {
            "weights_path": str(self._weights_path),
            "current_weights": current_weights,
            "new_weights": new_weights,
            "weight_adjustments": adjustments,
            "bucket_outcomes": bucket_outcomes,
            "metrics_synced": synced,
            "data_points": len(bucket_outcomes),
            "learned_feature_weights": learned_update,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        self._logger.info(
            f"Learning engine: {len(adjustments)} bucket adjustments, "
            f"{learned_update.get('actions_updated', 0)} learned-weight updates "
            f"across {learned_update.get('features_updated', 0)} features",
            extra={
                "adjustments": len(adjustments),
                "synced": synced,
                "learned_actions_updated": learned_update.get("actions_updated", 0),
                "learned_features_updated": learned_update.get("features_updated", 0),
            },
        )
        return items

    # ─── Step 5b: Learned feature weights (Phase 6) ─────────────────────

    def _update_learned_feature_weights(self, items: list[ProcessedItem]) -> dict:
        """Update learned feature weights from observed action outcomes.

        For each action in the SQLite actions table that has been marked
        'sent' or 'published' (i.e. has outcome data), extract its feature
        vector and call LearnedScorer.update().

        Returns a summary dict for the report.
        """
        try:
            from processors.learned_scorer import LearnedScorer
            from processors.feature_extractor import FeatureExtractor
            import sqlite3

            scorer = LearnedScorer(self._db_path)
            scorer.load()

            # Find the decisions data on items (so we can look up original decisions
            # to extract features — actions table only stores decision_type/target/priority)
            decisions_data = None
            for item in items:
                if "_decisions" in item.metadata:
                    decisions_data = item.metadata["_decisions"]
                    break

            # Build a lookup of decisions by ID (so we can reconstruct features)
            decisions_by_id = {}
            if decisions_data:
                for d in decisions_data.get("decisions", []):
                    if "id" in d:
                        decisions_by_id[d["id"]] = d
                # Also include filtered decisions (they may have outcomes too)
                for d in decisions_data.get("filtered", []):
                    if "id" in d:
                        decisions_by_id[d["id"]] = d

            # Query actions with outcome data
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT id, decision_type, target, priority, expected_impact,
                              clicks, signups, conversions, revenue, status
                       FROM actions
                       WHERE status IN ('sent', 'published')
                       AND (clicks > 0 OR signups > 0 OR conversions > 0 OR revenue > 0)"""
                ).fetchall()

            if not rows:
                return {
                    "actions_updated": 0,
                    "features_updated": 0,
                    "model_stats": scorer.get_stats(),
                    "message": "No actions with outcome data yet — learned weights unchanged.",
                }

            extractor = FeatureExtractor()
            actions_updated = 0
            features_touched: set[str] = set()
            errors: list[float] = []

            for row in rows:
                action_id = row["id"]

                # Reconstruct decision dict for feature extraction
                # Try to find original decision; if not found, build minimal one from action row
                decision = decisions_by_id.get(action_id)
                if not decision:
                    # Build a minimal decision from the action row
                    decision = {
                        "id": action_id,
                        "type": row["decision_type"],
                        "target": row["target"],
                        "priority": row["priority"],
                        "expected_impact": row["expected_impact"],
                        "evidence": [],  # we don't have evidence items for historical actions
                    }

                # Extract features
                features = extractor.extract(decision, items)

                # Compute outcome score (same formula as bucket outcomes)
                outcome = (
                    (row["clicks"] or 0) * 1
                    + (row["signups"] or 0) * 5
                    + (row["conversions"] or 0) * 25
                    + float(row["revenue"] or 0) * 0.1
                )

                # Update weights
                error = scorer.update(features, outcome)
                errors.append(error)
                actions_updated += 1
                features_touched.update(features.names)

            # Persist updated weights
            scorer.save()

            # Compute summary stats
            avg_error = sum(errors) / len(errors) if errors else 0
            abs_errors = [abs(e) for e in errors]
            mae = sum(abs_errors) / len(abs_errors) if abs_errors else 0  # Mean Absolute Error

            model_stats = scorer.get_stats()

            self._logger.info(
                f"Learned scorer: updated {actions_updated} actions, "
                f"touched {len(features_touched)} features, MAE={mae:.2f}"
            )

            return {
                "actions_updated": actions_updated,
                "features_updated": len(features_touched),
                "mean_absolute_error": round(mae, 2),
                "avg_prediction_error": round(avg_error, 2),
                "model_stats": model_stats,
                "feature_importance": scorer.get_feature_importance()[:10],  # top 10
                "message": f"Updated {actions_updated} weights. MAE: {mae:.2f}/100.",
            }

        except Exception as e:
            self._logger.error(f"Learned feature weight update failed: {e}", exc_info=True)
            return {
                "actions_updated": 0,
                "features_updated": 0,
                "error": str(e),
                "message": f"Learned weight update failed: {e}",
            }

    # ─── Step 1: Sync user metrics ──────────────────────────────────────

    def _sync_user_metrics(self) -> int:
        """Read metrics_input_template.json and update SQLite actions table."""
        if not self._metrics_input_path.exists():
            return 0

        try:
            with open(self._metrics_input_path, "r", encoding="utf-8") as f:
                template = json.load(f)
        except Exception as e:
            self._logger.warning(f"Could not read metrics template: {e}")
            return 0

        actions = template.get("actions", [])
        if not actions:
            return 0

        synced = 0
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            for action in actions:
                action_id = action.get("id")
                if not action_id:
                    continue
                try:
                    conn.execute(
                        """UPDATE actions
                           SET clicks = ?, signups = ?, conversions = ?,
                               revenue = ?, status = ?, notes = ?
                           WHERE id = ?""",
                        (
                            int(action.get("clicks", 0)),
                            int(action.get("signups", 0)),
                            int(action.get("conversions", 0)),
                            float(action.get("revenue", 0) or 0),
                            action.get("status", "draft"),
                            action.get("notes", ""),
                            action_id,
                        ),
                    )
                    synced += 1
                except Exception as e:
                    self._logger.warning(f"Failed to sync action {action_id}: {e}")
            conn.commit()
            conn.close()

        return synced

    # ─── Step 2: Load current weights ───────────────────────────────────

    def _load_current_weights(self) -> dict:
        if self._weights_path.exists():
            try:
                with open(self._weights_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Merge: current weights override defaults
                return {**_DEFAULT_THRESHOLDS, **{k: v for k, v in data.items() if k in _DEFAULT_THRESHOLDS}}
            except Exception as e:
                self._logger.warning(f"Could not load weights file: {e}")
        return dict(_DEFAULT_THRESHOLDS)

    # ─── Step 3: Compute bucket outcomes ────────────────────────────────

    def _compute_bucket_outcomes(self) -> list[dict]:
        """For each (decision_type, priority) bucket, compute avg outcome score."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT decision_type, priority,
                          SUM(clicks) AS clicks,
                          SUM(signups) AS signups,
                          SUM(conversions) AS conversions,
                          SUM(revenue) AS revenue,
                          COUNT(*) AS count
                   FROM actions
                   WHERE status IN ('sent', 'published')
                   GROUP BY decision_type, priority"""
            ).fetchall()
            conn.close()

        buckets: list[dict] = []
        for row in rows:
            outcome = (
                row["clicks"] * _OUTCOME_WEIGHTS["clicks"]
                + row["signups"] * _OUTCOME_WEIGHTS["signups"]
                + row["conversions"] * _OUTCOME_WEIGHTS["conversions"]
                + float(row["revenue"] or 0) * _OUTCOME_WEIGHTS["revenue"]
            )
            avg_outcome = outcome / row["count"] if row["count"] else 0
            buckets.append({
                "decision_type": row["decision_type"],
                "priority": row["priority"],
                "count": row["count"],
                "total_outcome": outcome,
                "avg_outcome": round(avg_outcome, 2),
            })
        return buckets

    # ─── Step 4: Compute adjustments ────────────────────────────────────

    def _compute_adjustments(self, current_weights: dict, buckets: list[dict]) -> tuple[list[dict], dict]:
        """Compute weight adjustments based on bucket performance.

        Strategy:
          - Compute overall avg outcome across all buckets (= baseline)
          - For each bucket, compute delta vs baseline
          - If bucket outperforms (delta > +20%) → lower the threshold that triggers
            this type/priority (make it easier to fire)
          - If bucket underperforms (delta < -20%) → raise the threshold (harder to fire)
          - Cap adjustment per cycle at _MAX_ADJUSTMENT

        Threshold mapping (which threshold controls which type/priority):
          - build_feature P0 ← opportunity_high, weakness_high
          - launch_campaign P1 ← opportunity_medium
          - write_content P1/P2 ← trend_hot
          - reach_out P1 ← (no direct threshold; skip)
          - monitor_competitor P1/P2 ← threat_high, threat_medium
        """
        if not buckets:
            return [], dict(current_weights)

        # Overall baseline
        total_outcome = sum(b["total_outcome"] for b in buckets)
        total_count = sum(b["count"] for b in buckets)
        baseline = total_outcome / total_count if total_count else 0

        if baseline == 0:
            # No outcome data yet — no adjustments
            return [], dict(current_weights)

        # Map (decision_type, priority) → list of thresholds that gate it
        threshold_map = {
            ("build_feature", "P0"): ["opportunity_high", "weakness_high"],
            ("launch_campaign", "P1"): ["opportunity_medium"],
            ("write_content", "P1"): ["trend_hot"],
            ("write_content", "P2"): ["trend_hot"],
            ("monitor_competitor", "P1"): ["threat_high"],
            ("monitor_competitor", "P2"): ["threat_medium"],
        }

        adjustments: list[dict] = []
        new_weights = dict(current_weights)

        for bucket in buckets:
            key = (bucket["decision_type"], bucket["priority"])
            thresholds = threshold_map.get(key)
            if not thresholds:
                continue

            delta_pct = (bucket["avg_outcome"] - baseline) / baseline

            # Only adjust if delta exceeds threshold
            if abs(delta_pct) < _PERFORMANCE_DELTA:
                continue

            for threshold_name in thresholds:
                old_value = new_weights.get(threshold_name, _DEFAULT_THRESHOLDS[threshold_name])

                # Outperform → lower threshold (easier to trigger)
                # Underperform → raise threshold (harder to trigger)
                direction = -1 if delta_pct > 0 else 1
                raw_adjustment = direction * min(_MAX_ADJUSTMENT, int(abs(delta_pct) * 20))
                if raw_adjustment == 0:
                    continue

                new_value = max(5, min(95, old_value + raw_adjustment))
                if new_value == old_value:
                    continue

                adjustments.append({
                    "decision_type": bucket["decision_type"],
                    "priority": bucket["priority"],
                    "threshold": threshold_name,
                    "old_value": old_value,
                    "new_value": new_value,
                    "avg_outcome": bucket["avg_outcome"],
                    "baseline_outcome": round(baseline, 2),
                    "delta_pct": round(delta_pct, 3),
                    "action": (
                        f"{'lowered' if new_value < old_value else 'raised'} "
                        f"{threshold_name} from {old_value} to {new_value}"
                    ),
                    "sample_size": bucket["count"],
                })
                new_weights[threshold_name] = new_value

        return adjustments, new_weights

    # ─── Step 5: Save weights ───────────────────────────────────────────

    def _save_weights(self, weights: dict, adjustments: list[dict], data_points: int) -> None:
        payload = {
            **weights,
            "weight_adjustments": adjustments,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "data_points": data_points,
        }
        try:
            self._weights_path.parent.mkdir(parents=True, exist_ok=True)
            self._weights_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            self._logger.error(f"Failed to save weights: {e}")
