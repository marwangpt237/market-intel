"""
Collector Health Monitor — tracks success rate, latency, rate limits per collector.

Records every collect() call result and computes:
  - success_rate (successes / total_calls)
  - avg_latency_ms
  - consecutive_failures
  - total_items_collected
  - last_error

Status determination:
  - healthy: success_rate >= 0.90, consecutive_failures < 3
  - degraded: success_rate >= 0.50, consecutive_failures < 5
  - down: success_rate < 0.50 OR consecutive_failures >= 5

Persisted to SQLite so health survives across runs.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from core.logger import get_logger
from collectors.marketplace.base import CollectorHealth


_HEALTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS collector_health (
    collector_name TEXT PRIMARY KEY,
    status TEXT DEFAULT 'unknown',
    last_success TEXT,
    last_failure TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    total_calls INTEGER DEFAULT 0,
    total_successes INTEGER DEFAULT 0,
    total_failures INTEGER DEFAULT 0,
    total_items_collected INTEGER DEFAULT 0,
    avg_latency_ms REAL DEFAULT 0.0,
    last_error TEXT,
    success_rate REAL DEFAULT 0.0,
    last_health_check TEXT,
    updated_at TEXT NOT NULL
);
"""


class CollectorHealthMonitor:
    """Tracks health metrics for all collectors.

    Usage:
        monitor = CollectorHealthMonitor(db_path)
        monitor.record_success("ouedkniss", latency_ms=450, items_collected=25)
        monitor.record_failure("ouedkniss", error="HTTP 429")
        health = monitor.get_health("ouedkniss")
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._logger = get_logger("collector_health_monitor")

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.executescript(_HEALTH_SCHEMA)
            conn.commit()
            conn.close()

    def record_success(
        self,
        collector_name: str,
        latency_ms: float,
        items_collected: int,
    ) -> None:
        """Record a successful collect() call."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row

            # Get current state
            row = conn.execute(
                "SELECT * FROM collector_health WHERE collector_name = ?",
                (collector_name,)
            ).fetchone()

            if row is None:
                # Insert new
                total_calls = 1
                total_successes = 1
                total_items = items_collected
                avg_latency = latency_ms
            else:
                total_calls = row["total_calls"] + 1
                total_successes = row["total_successes"] + 1
                total_items = row["total_items_collected"] + items_collected
                # Rolling average latency
                avg_latency = ((row["avg_latency_ms"] * row["total_calls"]) + latency_ms) / total_calls

            success_rate = total_successes / total_calls if total_calls > 0 else 0.0
            status = self._compute_status(success_rate, 0)  # consecutive_failures reset to 0

            conn.execute(
                """INSERT INTO collector_health
                   (collector_name, status, last_success, consecutive_failures,
                    total_calls, total_successes, total_failures, total_items_collected,
                    avg_latency_ms, success_rate, last_health_check, updated_at)
                   VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(collector_name) DO UPDATE SET
                     status = excluded.status,
                     last_success = excluded.last_success,
                     consecutive_failures = 0,
                     total_calls = excluded.total_calls,
                     total_successes = excluded.total_successes,
                     total_items_collected = excluded.total_items_collected,
                     avg_latency_ms = excluded.avg_latency_ms,
                     success_rate = excluded.success_rate,
                     last_health_check = excluded.last_health_check,
                     updated_at = excluded.updated_at""",
                (collector_name, status, now, total_calls, total_successes,
                 0, total_items, avg_latency, success_rate, now, now),
            )
            conn.commit()
            conn.close()

    def record_failure(
        self,
        collector_name: str,
        error: str,
        latency_ms: float = 0.0,
    ) -> None:
        """Record a failed collect() call."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row

            row = conn.execute(
                "SELECT * FROM collector_health WHERE collector_name = ?",
                (collector_name,)
            ).fetchone()

            if row is None:
                total_calls = 1
                total_failures = 1
                consecutive_failures = 1
                total_successes = 0
                avg_latency = latency_ms
            else:
                total_calls = row["total_calls"] + 1
                total_failures = row["total_failures"] + 1
                consecutive_failures = row["consecutive_failures"] + 1
                total_successes = row["total_successes"]
                avg_latency = ((row["avg_latency_ms"] * row["total_calls"]) + latency_ms) / total_calls

            success_rate = total_successes / total_calls if total_calls > 0 else 0.0
            status = self._compute_status(success_rate, consecutive_failures)

            conn.execute(
                """INSERT INTO collector_health
                   (collector_name, status, last_failure, consecutive_failures,
                    total_calls, total_successes, total_failures, total_items_collected,
                    avg_latency_ms, last_error, success_rate, last_health_check, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                   ON CONFLICT(collector_name) DO UPDATE SET
                     status = excluded.status,
                     last_failure = excluded.last_failure,
                     consecutive_failures = excluded.consecutive_failures,
                     total_calls = excluded.total_calls,
                     total_successes = excluded.total_successes,
                     total_failures = excluded.total_failures,
                     avg_latency_ms = excluded.avg_latency_ms,
                     last_error = excluded.last_error,
                     success_rate = excluded.success_rate,
                     last_health_check = excluded.last_health_check,
                     updated_at = excluded.updated_at""",
                (collector_name, status, now, consecutive_failures, total_calls,
                 total_successes, total_failures, avg_latency, error, success_rate, now, now),
            )
            conn.commit()
            conn.close()

    def get_health(self, collector_name: str) -> CollectorHealth:
        """Get health metrics for a collector."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM collector_health WHERE collector_name = ?",
                (collector_name,)
            ).fetchone()
            conn.close()

        if row is None:
            return CollectorHealth(collector_name=collector_name, status="unknown")

        return CollectorHealth(
            collector_name=row["collector_name"],
            status=row["status"],
            last_success=row["last_success"],
            last_failure=row["last_failure"],
            consecutive_failures=row["consecutive_failures"],
            total_calls=row["total_calls"],
            total_successes=row["total_successes"],
            total_failures=row["total_failures"],
            total_items_collected=row["total_items_collected"],
            avg_latency_ms=row["avg_latency_ms"],
            last_error=row["last_error"],
            success_rate=row["success_rate"],
            last_health_check=row["last_health_check"],
        )

    def get_all_health(self) -> dict[str, CollectorHealth]:
        """Get health metrics for all collectors."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM collector_health").fetchall()
            conn.close()

        result = {}
        for row in rows:
            result[row["collector_name"]] = CollectorHealth(
                collector_name=row["collector_name"],
                status=row["status"],
                last_success=row["last_success"],
                last_failure=row["last_failure"],
                consecutive_failures=row["consecutive_failures"],
                total_calls=row["total_calls"],
                total_successes=row["total_successes"],
                total_failures=row["total_failures"],
                total_items_collected=row["total_items_collected"],
                avg_latency_ms=row["avg_latency_ms"],
                last_error=row["last_error"],
                success_rate=row["success_rate"],
                last_health_check=row["last_health_check"],
            )
        return result

    def get_stats(self) -> dict:
        """Get aggregate health stats."""
        all_health = self.get_all_health()
        from collections import Counter
        status_counts = Counter(h.status for h in all_health.values())
        total_items = sum(h.total_items_collected for h in all_health.values())
        avg_success_rate = (
            sum(h.success_rate for h in all_health.values()) / len(all_health)
            if all_health else 0.0
        )
        return {
            "total_collectors_tracked": len(all_health),
            "by_status": dict(status_counts),
            "total_items_collected_all_time": total_items,
            "avg_success_rate": round(avg_success_rate, 3),
        }

    @staticmethod
    def _compute_status(success_rate: float, consecutive_failures: int) -> str:
        """Compute health status from success rate + consecutive failures.

        consecutive_failures takes priority for "down" — a single failure
        with no prior history should not immediately mark down.
        """
        if consecutive_failures >= 5:
            return "down"
        elif consecutive_failures >= 3:
            return "degraded"
        elif success_rate < 0.50 and consecutive_failures >= 2:
            return "down"
        elif success_rate < 0.90 and consecutive_failures >= 1:
            return "degraded"
        elif success_rate >= 0.90:
            return "healthy"
        elif success_rate > 0:
            return "degraded"
        else:
            # success_rate == 0 but no consecutive failures tracked yet
            return "unknown" if consecutive_failures == 0 else "degraded"
