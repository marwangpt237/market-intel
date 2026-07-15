"""
Analytics Engine — Phase 4 module.

Records every executed action in a dedicated SQLite table (`actions`) and
exposes an outcome-tracking interface. Each action starts with status=draft
and metrics=0. The user (or a future tracking pixel / webhook) updates
metrics as outcomes are observed.

Schema (added to market_intel.db):
  actions(
    id TEXT PRIMARY KEY,            -- matches decision_id
    decision_type TEXT,             -- build_feature | launch_campaign | ...
    target TEXT,                    -- entity the action targets
    priority TEXT,
    expected_impact TEXT,
    artifact_path TEXT,             -- path to generated markdown
    created_at TEXT,
    status TEXT,                    -- draft | sent | published | paused | abandoned
    clicks INTEGER DEFAULT 0,
    signups INTEGER DEFAULT 0,
    conversions INTEGER DEFAULT 0,
    revenue REAL DEFAULT 0,
    notes TEXT
  )

The engine also writes a `metrics_input_template.json` file with zero-valued
metric slots for each new action — the user fills these in manually (for now)
and the Learning Engine reads them on the next run.

Future: replace the manual template with UTM tracking pixels + a webhook
endpoint that ingests Stripe / analytics events.
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


_ACTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY,
    decision_type TEXT NOT NULL,
    target TEXT NOT NULL,
    priority TEXT,
    expected_impact TEXT,
    artifact_path TEXT,
    created_at TEXT NOT NULL,
    status TEXT DEFAULT 'draft',
    clicks INTEGER DEFAULT 0,
    signups INTEGER DEFAULT 0,
    conversions INTEGER DEFAULT 0,
    revenue REAL DEFAULT 0,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_actions_type ON actions(decision_type);
CREATE INDEX IF NOT EXISTS idx_actions_target ON actions(target);
CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status);
CREATE INDEX IF NOT EXISTS idx_actions_created ON actions(created_at);
"""


class AnalyticsEngine(BaseProcessor):
    name = "analytics_engine"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        storage_cfg = self._config.get("storage", {})
        self._db_path = storage_cfg.get("path", "data/market_intel.db")
        self._metrics_input_path = Path(self._db_path).parent / "metrics_input_template.json"
        self._lock = threading.Lock()
        # Ensure schema exists
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.executescript(_ACTIONS_SCHEMA)
            conn.commit()
            conn.close()

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        if not items:
            return items

        executions_data = None
        for item in items:
            if "_executions" in item.metadata:
                executions_data = item.metadata["_executions"]
                break

        if not executions_data:
            self._logger.info("No executions to record — skipping analytics engine")
            return items

        artifacts = executions_data.get("artifacts", [])
        decisions_by_id = self._index_decisions(items)

        recorded = 0
        new_action_ids: list[str] = []
        for artifact in artifacts:
            decision_id = artifact.get("decision_id", "")
            if not decision_id:
                continue
            decision = decisions_by_id.get(decision_id, {})
            recorded += self._record_action(
                action_id=decision_id,
                decision_type=artifact.get("type", ""),
                target=decision.get("target", ""),
                priority=decision.get("priority", ""),
                expected_impact=decision.get("expected_impact", ""),
                artifact_path=artifact.get("path", ""),
            )
            if recorded:
                new_action_ids.append(decision_id)

        # Generate / update metrics input template
        metrics_template = self._build_metrics_template()
        self._write_metrics_template(metrics_template)

        # Build analytics summary
        summary = self._build_summary()

        items[0].metadata["_analytics"] = {
            "actions_recorded_this_run": recorded,
            "new_action_ids": new_action_ids,
            "total_actions_in_db": summary["total_actions"],
            "actions_by_status": summary["by_status"],
            "actions_by_type": summary["by_type"],
            "metrics_input_path": str(self._metrics_input_path),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        self._logger.info(
            f"Analytics: {recorded} new actions recorded, {summary['total_actions']} total in DB",
            extra=summary,
        )
        return items

    # ─── DB operations ───────────────────────────────────────────────────

    def _record_action(
        self,
        action_id: str,
        decision_type: str,
        target: str,
        priority: str,
        expected_impact: str,
        artifact_path: str,
    ) -> int:
        """Insert action if new; return 1 if inserted, 0 if already existed."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                # Check if action already exists
                existing = conn.execute(
                    "SELECT id FROM actions WHERE id = ?", (action_id,)
                ).fetchone()

                if existing:
                    # Update artifact path / metadata only — preserve metrics
                    conn.execute(
                        """UPDATE actions
                           SET artifact_path = ?, priority = ?, expected_impact = ?
                           WHERE id = ?""",
                        (artifact_path, priority, expected_impact, action_id),
                    )
                    conn.commit()
                    return 0

                conn.execute(
                    """INSERT INTO actions
                       (id, decision_type, target, priority, expected_impact,
                        artifact_path, created_at, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'draft')""",
                    (action_id, decision_type, target, priority, expected_impact,
                     artifact_path, datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
                return 1
            finally:
                conn.close()

    def _build_metrics_template(self) -> dict:
        """Build a JSON template the user can fill in to update metrics.

        For each action with status='draft' or 'sent', include slots for
        clicks / signups / conversions / revenue / status / notes.
        Existing metrics are pre-filled so the user only updates changed values.
        """
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT id, decision_type, target, priority, status,
                          clicks, signups, conversions, revenue, notes, created_at
                   FROM actions
                   WHERE status IN ('draft', 'sent', 'published')
                   ORDER BY created_at DESC
                   LIMIT 50"""
            ).fetchall()
            conn.close()

        template = {
            "_instructions": (
                "Fill in the metrics for each action below, then save this file. "
                "The Learning Engine will read it on the next run and adjust scoring weights. "
                "Set status to 'sent' once you send/publish, 'published' once live, "
                "'abandoned' to drop, 'paused' to defer."
            ),
            "actions": [],
        }
        for row in rows:
            template["actions"].append({
                "id": row["id"],
                "target": row["target"],
                "type": row["decision_type"],
                "current_status": row["status"],
                "clicks": row["clicks"],
                "signups": row["signups"],
                "conversions": row["conversions"],
                "revenue": row["revenue"],
                "status": row["status"],  # user can change
                "notes": row["notes"] or "",
            })
        return template

    def _write_metrics_template(self, template: dict) -> None:
        try:
            self._metrics_input_path.write_text(
                json.dumps(template, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            self._logger.error(f"Failed to write metrics template: {e}")

    def _build_summary(self) -> dict:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row

            total = conn.execute("SELECT COUNT(*) AS c FROM actions").fetchone()["c"]

            by_status_rows = conn.execute(
                "SELECT status, COUNT(*) AS c FROM actions GROUP BY status"
            ).fetchall()
            by_status = {r["status"]: r["c"] for r in by_status_rows}

            by_type_rows = conn.execute(
                "SELECT decision_type, COUNT(*) AS c FROM actions GROUP BY decision_type"
            ).fetchall()
            by_type = {r["decision_type"]: r["c"] for r in by_type_rows}

            # Aggregate metrics
            agg = conn.execute(
                """SELECT
                       COALESCE(SUM(clicks), 0) AS clicks,
                       COALESCE(SUM(signups), 0) AS signups,
                       COALESCE(SUM(conversions), 0) AS conversions,
                       COALESCE(SUM(revenue), 0) AS revenue
                   FROM actions"""
            ).fetchone()

            conn.close()

        return {
            "total_actions": total,
            "by_status": by_status,
            "by_type": by_type,
            "totals": {
                "clicks": agg["clicks"],
                "signups": agg["signups"],
                "conversions": agg["conversions"],
                "revenue": float(agg["revenue"] or 0),
            },
        }

    # ─── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _index_decisions(items: list[ProcessedItem]) -> dict[str, dict]:
        """Build a {decision_id: decision_dict} index from items' metadata."""
        for item in items:
            decisions_data = item.metadata.get("_decisions")
            if decisions_data and isinstance(decisions_data, dict):
                return {d["id"]: d for d in decisions_data.get("decisions", []) if "id" in d}
        return {}
