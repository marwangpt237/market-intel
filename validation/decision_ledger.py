"""
Decision Ledger — append-only log of decisions + claim IDs that justify them.

Every decision/recommendation produced by the platform must be logged
to the Decision Ledger with:
  - Decision ID
  - Decision type + target
  - Claim IDs that justify the decision
  - Confidence of the decision (computed from claim confidences)
  - Warnings (weak claims, conflicting claims, missing evidence)
  - Timestamp

This creates an audit trail: for any recommendation the platform makes,
you can trace back to the specific claims + evidence that justified it.

Schema:
  decision_ledger(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL,
    decision_type TEXT,
    target TEXT,
    priority TEXT,
    suggested_action TEXT,
    claim_ids TEXT,             -- JSON array of claim IDs
    claim_confidences TEXT,     -- JSON array of {claim_id, confidence, status}
    decision_confidence REAL,
    warnings TEXT,              -- JSON array of warning strings
    timestamp TEXT NOT NULL
  )
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from core.logger import get_logger


_LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS decision_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL,
    decision_type TEXT,
    target TEXT,
    priority TEXT,
    suggested_action TEXT,
    claim_ids TEXT,
    claim_confidences TEXT,
    decision_confidence REAL,
    warnings TEXT,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ledger_decision_id ON decision_ledger(decision_id);
CREATE INDEX IF NOT EXISTS idx_ledger_timestamp ON decision_ledger(timestamp);
CREATE INDEX IF NOT EXISTS idx_ledger_confidence ON decision_ledger(decision_confidence);
"""


class DecisionLedger:
    """Append-only log of decisions + their supporting claims.

    The Decision Engine / Strategy Engine call ledger.record_decision()
    for each decision they produce. The ledger looks up the claim IDs
    that justify the decision, computes a decision_confidence, and
    records any warnings (weak claims, conflicts, missing evidence).
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._logger = get_logger("decision_ledger")

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.executescript(_LEDGER_SCHEMA)
            conn.commit()
            conn.close()

    def record_decision(
        self,
        decision_id: str,
        decision_type: str,
        target: str,
        priority: str,
        suggested_action: str,
        claim_ids: list[str],
        claim_confidences: list[dict],
        decision_confidence: float,
        warnings: list[str],
    ) -> None:
        """Record a decision in the ledger.

        Args:
            decision_id: Stable decision ID
            decision_type: build_feature, launch_campaign, etc.
            target: Entity the decision targets
            priority: P0/P1/P2/P3
            suggested_action: The action suggested
            claim_ids: List of Claim IDs that justify this decision
            claim_confidences: List of {claim_id, confidence, status, claim_type} dicts
            decision_confidence: Computed confidence (0-1) based on claim confidences
            warnings: List of warning strings (weak claims, conflicts, etc.)
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                """INSERT INTO decision_ledger
                   (decision_id, decision_type, target, priority, suggested_action,
                    claim_ids, claim_confidences, decision_confidence, warnings, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    decision_id,
                    decision_type,
                    target,
                    priority,
                    suggested_action,
                    json.dumps(claim_ids),
                    json.dumps(claim_confidences),
                    decision_confidence,
                    json.dumps(warnings),
                    now,
                ),
            )
            conn.commit()
            conn.close()

        self._logger.info(
            f"Decision recorded: {decision_id} ({decision_type} → {target}) "
            f"confidence={decision_confidence:.2f} claims={len(claim_ids)} warnings={len(warnings)}"
        )

    def get_decision(self, decision_id: str) -> dict | None:
        """Get a single decision by ID."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM decision_ledger WHERE decision_id = ? ORDER BY timestamp DESC LIMIT 1",
                (decision_id,)
            ).fetchone()
            conn.close()
        return self._row_to_dict(row) if row else None

    def get_recent_decisions(self, limit: int = 50) -> list[dict]:
        """Get recent decisions, most recent first."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM decision_ledger ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
            conn.close()
        return [self._row_to_dict(r) for r in rows]

    def get_decisions_with_warnings(self, limit: int = 50) -> list[dict]:
        """Get decisions that have warnings (weak claims, conflicts, etc.)."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM decision_ledger WHERE warnings != '[]' ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
            conn.close()
        return [self._row_to_dict(r) for r in rows]

    def get_low_confidence_decisions(self, threshold: float = 0.40, limit: int = 50) -> list[dict]:
        """Get decisions with confidence below threshold."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM decision_ledger WHERE decision_confidence < ? ORDER BY timestamp DESC LIMIT ?",
                (threshold, limit)
            ).fetchall()
            conn.close()
        return [self._row_to_dict(r) for r in rows]

    def get_stats(self) -> dict:
        """Get aggregate stats about the decision ledger."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            total = conn.execute("SELECT COUNT(*) AS c FROM decision_ledger").fetchone()["c"]
            with_warnings = conn.execute(
                "SELECT COUNT(*) AS c FROM decision_ledger WHERE warnings != '[]'"
            ).fetchone()["c"]
            avg_conf = conn.execute(
                "SELECT AVG(decision_confidence) AS avg FROM decision_ledger"
            ).fetchone()["avg"] or 0.0
            low_conf = conn.execute(
                "SELECT COUNT(*) AS c FROM decision_ledger WHERE decision_confidence < 0.40"
            ).fetchone()["c"]
            conn.close()

        return {
            "total_decisions": total,
            "decisions_with_warnings": with_warnings,
            "low_confidence_decisions": low_conf,
            "avg_confidence": round(avg_conf, 3),
        }

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["claim_ids"] = json.loads(d.get("claim_ids") or "[]")
        d["claim_confidences"] = json.loads(d.get("claim_confidences") or "[]")
        d["warnings"] = json.loads(d.get("warnings") or "[]")
        return d


def compute_decision_confidence(claim_confidences: list[dict]) -> tuple[float, list[str]]:
    """Compute decision confidence from the confidences of its supporting claims.

    Args:
        claim_confidences: List of {claim_id, confidence, status, claim_type} dicts

    Returns:
        (decision_confidence 0-1, list of warning strings)
    """
    if not claim_confidences:
        return 0.0, ["No supporting claims"]

    warnings: list[str] = []
    total_weight = 0.0
    total_confidence = 0.0

    for cc in claim_confidences:
        confidence = cc.get("confidence", 0.0)
        status = cc.get("status", "UNKNOWN")

        # Weight: VERIFIED > PROBABLE > HYPOTHESIS > others
        weight = {
            "VERIFIED": 1.0,
            "PROBABLE": 0.7,
            "HYPOTHESIS": 0.4,
            "CONFLICTED": 0.1,
            "EXPIRED": 0.0,
            "UNKNOWN": 0.1,
        }.get(status, 0.1)

        if status == "CONFLICTED":
            warnings.append(f"Claim {cc.get('claim_id', '?')} is CONFLICTED — contradicting evidence present")
        elif status == "EXPIRED":
            warnings.append(f"Claim {cc.get('claim_id', '?')} is EXPIRED — evidence is stale")
        elif status == "HYPOTHESIS":
            warnings.append(f"Claim {cc.get('claim_id', '?')} is HYPOTHESIS — only single source")
        elif status == "UNKNOWN":
            warnings.append(f"Claim {cc.get('claim_id', '?')} is UNKNOWN — no validated evidence")
        # Low-confidence warning fires in addition to status warning
        if confidence < 0.40:
            warnings.append(f"Claim {cc.get('claim_id', '?')} has low confidence ({confidence:.2f})")

        total_weight += weight
        total_confidence += confidence * weight

    if total_weight == 0:
        return 0.0, warnings + ["All supporting claims have zero weight"]

    decision_confidence = total_confidence / total_weight
    return round(decision_confidence, 3), warnings
