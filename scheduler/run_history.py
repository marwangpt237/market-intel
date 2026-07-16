"""
Run History Store — SQLite-persisted run history.

Tracks every pipeline run with:
  - run_id, job_id, profile, status
  - started_at, completed_at, duration_seconds
  - items_collected, items_processed
  - error, traceback (on failure)
  - summary (JSON — full DailyRun summary)
  - retry_count, next_retry_at

Enables the API to show run history + metrics across restarts.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from core.logger import get_logger


_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    job_id TEXT,
    profile TEXT NOT NULL,
    status TEXT NOT NULL,
    triggered_by TEXT DEFAULT 'manual',  -- manual, scheduled, retry
    started_at TEXT NOT NULL,
    completed_at TEXT,
    duration_seconds REAL,
    items_collected INTEGER DEFAULT 0,
    items_processed INTEGER DEFAULT 0,
    reports_generated INTEGER DEFAULT 0,
    error TEXT,
    traceback TEXT,
    summary TEXT,                        -- JSON
    retry_count INTEGER DEFAULT 0,
    next_retry_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_history_run_id ON run_history(run_id);
CREATE INDEX IF NOT EXISTS idx_run_history_status ON run_history(status);
CREATE INDEX IF NOT EXISTS idx_run_history_started ON run_history(started_at);
CREATE INDEX IF NOT EXISTS idx_run_history_profile ON run_history(profile);
"""


class RunHistoryStore:
    """SQLite-persisted run history."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._logger = get_logger("run_history_store")

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.executescript(_SCHEMA)
            conn.commit()
            conn.close()

    def record_start(
        self,
        run_id: str,
        profile: str,
        job_id: str | None = None,
        triggered_by: str = "manual",
    ) -> None:
        """Record the start of a run."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                """INSERT INTO run_history
                   (run_id, job_id, profile, status, triggered_by, started_at, created_at)
                   VALUES (?, ?, ?, 'running', ?, ?, ?)""",
                (run_id, job_id, profile, triggered_by, now, now),
            )
            conn.commit()
            conn.close()

    def record_completion(
        self,
        run_id: str,
        status: str,
        summary: dict | None = None,
        error: str | None = None,
        traceback_str: str | None = None,
    ) -> None:
        """Record the completion of a run."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row

            # Get started_at to compute duration
            row = conn.execute(
                "SELECT started_at FROM run_history WHERE run_id = ? ORDER BY id DESC LIMIT 1",
                (run_id,)
            ).fetchone()

            duration = None
            if row and row["started_at"]:
                try:
                    started = datetime.fromisoformat(row["started_at"])
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                    duration = (datetime.now(timezone.utc) - started).total_seconds()
                except Exception:
                    pass

            # Extract counts from summary
            items_collected = 0
            items_processed = 0
            reports_generated = 0
            if summary:
                items_collected = sum(summary.get("collectors", {}).values()) if isinstance(summary.get("collectors"), dict) else 0
                items_processed = summary.get("total_items", 0)
                reports_generated = sum(1 for k, v in summary.items() if k.endswith("_report_path") and v)

            # Get the most recent running record for this run_id
            row = conn.execute(
                "SELECT id FROM run_history WHERE run_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1",
                (run_id,)
            ).fetchone()
            if row is None:
                conn.close()
                return

            conn.execute(
                """UPDATE run_history
                   SET status = ?, completed_at = ?, duration_seconds = ?,
                       items_collected = ?, items_processed = ?, reports_generated = ?,
                       error = ?, traceback = ?, summary = ?
                   WHERE id = ?""",
                (
                    status,
                    now,
                    duration,
                    items_collected,
                    items_processed,
                    reports_generated,
                    error,
                    traceback_str,
                    json.dumps(summary, default=str) if summary else None,
                    row["id"],
                ),
            )
            conn.commit()
            conn.close()

    def record_retry(self, run_id: str, retry_count: int, next_retry_at: str) -> None:
        """Record that a run is being retried."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                """UPDATE run_history
                   SET status = 'retrying', retry_count = ?, next_retry_at = ?
                   WHERE run_id = ? AND status = 'running'
                   ORDER BY id DESC LIMIT 1""",
                (retry_count, next_retry_at, run_id),
            )
            conn.commit()
            conn.close()

    def get_run(self, run_id: str) -> dict | None:
        """Get a single run by ID."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM run_history WHERE run_id = ? ORDER BY id DESC LIMIT 1",
                (run_id,)
            ).fetchone()
            conn.close()

        if not row:
            return None
        result = dict(row)
        if result.get("summary"):
            try:
                result["summary"] = json.loads(result["summary"])
            except Exception:
                pass
        return result

    def get_recent_runs(self, limit: int = 20, status: str | None = None) -> list[dict]:
        """Get recent runs, optionally filtered by status."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row

            if status:
                rows = conn.execute(
                    "SELECT * FROM run_history WHERE status = ? ORDER BY started_at DESC LIMIT ?",
                    (status, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM run_history ORDER BY started_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            conn.close()

        results = []
        for row in rows:
            r = dict(row)
            if r.get("summary"):
                try:
                    r["summary"] = json.loads(r["summary"])
                except Exception:
                    pass
            results.append(r)
        return results

    def get_stats(self) -> dict:
        """Get aggregate run stats."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row

            total = conn.execute("SELECT COUNT(*) AS c FROM run_history").fetchone()["c"]
            by_status_rows = conn.execute(
                "SELECT status, COUNT(*) AS c FROM run_history GROUP BY status"
            ).fetchall()
            by_status = {r["status"]: r["c"] for r in by_status_rows}

            avg_duration = conn.execute(
                "SELECT AVG(duration_seconds) AS avg FROM run_history WHERE duration_seconds IS NOT NULL"
            ).fetchone()["avg"] or 0.0

            total_items = conn.execute(
                "SELECT COALESCE(SUM(items_collected), 0) AS s FROM run_history"
            ).fetchone()["s"]

            success_rate = 0.0
            if total > 0:
                completed = by_status.get("completed", 0)
                success_rate = completed / total

            conn.close()

        return {
            "total_runs": total,
            "by_status": by_status,
            "avg_duration_seconds": round(avg_duration, 2),
            "total_items_collected": total_items,
            "success_rate": round(success_rate, 3),
        }

    def get_active_runs(self) -> list[dict]:
        """Get currently-running + retrying runs."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM run_history WHERE status IN ('running', 'retrying', 'cancelling') ORDER BY started_at DESC"
            ).fetchall()
            conn.close()
        return [dict(row) for row in rows]
