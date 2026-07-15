"""
Feature Weights Store — SQLite persistence for learned weights.

Schema:
  feature_weights(
    feature_name TEXT PRIMARY KEY,
    weight REAL NOT NULL,
    baseline_weight REAL NOT NULL,   -- original heuristic, for cold-start fallback
    samples INTEGER DEFAULT 0,       -- number of outcome observations used to update this weight
    total_gradient REAL DEFAULT 0,   -- sum of absolute gradients applied (for diagnostics)
    last_updated TEXT NOT NULL
  )

Also stores a single row for the bias term:
  feature_name = '__bias__'
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from core.logger import get_logger


_SCHEMA = """
CREATE TABLE IF NOT EXISTS feature_weights (
    feature_name TEXT PRIMARY KEY,
    weight REAL NOT NULL,
    baseline_weight REAL NOT NULL,
    samples INTEGER DEFAULT 0,
    total_gradient REAL DEFAULT 0,
    last_updated TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feature_weights_samples ON feature_weights(samples);
"""


class FeatureWeightsStore:
    """SQLite-backed store for learned feature weights."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._logger = get_logger("feature_weights_store")

        # Ensure parent dir + schema exist
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.executescript(_SCHEMA)
            conn.commit()
            conn.close()

    def load_all(self) -> dict[str, dict]:
        """Load all feature weights.

        Returns: {feature_name: {weight, baseline_weight, samples, total_gradient, last_updated}}
        """
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT feature_name, weight, baseline_weight, samples, total_gradient, last_updated FROM feature_weights"
            ).fetchall()
            conn.close()

        return {
            row["feature_name"]: {
                "weight": row["weight"],
                "baseline_weight": row["baseline_weight"],
                "samples": row["samples"],
                "total_gradient": row["total_gradient"],
                "last_updated": row["last_updated"],
            }
            for row in rows
        }

    def get_weight(self, feature_name: str) -> Optional[dict]:
        """Get a single feature's weight record."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM feature_weights WHERE feature_name = ?",
                (feature_name,)
            ).fetchone()
            conn.close()

        return dict(row) if row else None

    def upsert(
        self,
        feature_name: str,
        weight: float,
        baseline_weight: float,
        samples: int,
        total_gradient: float = 0.0,
    ) -> None:
        """Insert or update a feature weight."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                """INSERT INTO feature_weights
                   (feature_name, weight, baseline_weight, samples, total_gradient, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(feature_name) DO UPDATE SET
                     weight = excluded.weight,
                     baseline_weight = excluded.baseline_weight,
                     samples = excluded.samples,
                     total_gradient = excluded.total_gradient,
                     last_updated = excluded.last_updated""",
                (feature_name, weight, baseline_weight, samples, total_gradient, now),
            )
            conn.commit()
            conn.close()

    def increment_and_update(
        self,
        feature_name: str,
        new_weight: float,
        baseline_weight: float,
        gradient_abs: float,
    ) -> None:
        """Increment sample count and update weight + total_gradient."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                """INSERT INTO feature_weights
                   (feature_name, weight, baseline_weight, samples, total_gradient, last_updated)
                   VALUES (?, ?, ?, 1, ?, ?)
                   ON CONFLICT(feature_name) DO UPDATE SET
                     weight = excluded.weight,
                     baseline_weight = COALESCE(NULLIF(feature_weights.baseline_weight, 0), excluded.baseline_weight),
                     samples = feature_weights.samples + 1,
                     total_gradient = feature_weights.total_gradient + excluded.total_gradient,
                     last_updated = excluded.last_updated""",
                (feature_name, new_weight, baseline_weight, gradient_abs, now),
            )
            conn.commit()
            conn.close()

    def get_stats(self) -> dict:
        """Get aggregate stats about the weight store."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            total = conn.execute("SELECT COUNT(*) AS c FROM feature_weights").fetchone()["c"]
            with_samples = conn.execute(
                "SELECT COUNT(*) AS c FROM feature_weights WHERE samples > 0"
            ).fetchone()["c"]
            with_enough_samples = conn.execute(
                "SELECT COUNT(*) AS c FROM feature_weights WHERE samples >= 5"
            ).fetchone()["c"]
            total_samples = conn.execute(
                "SELECT COALESCE(SUM(samples), 0) AS s FROM feature_weights"
            ).fetchone()["s"]
            conn.close()

        return {
            "total_features": total,
            "features_with_samples": with_samples,
            "features_with_enough_samples": with_enough_samples,
            "total_samples": total_samples,
        }

    def reset_all(self) -> None:
        """Reset all weights to baseline. Use for debugging/testing."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute("DELETE FROM feature_weights")
            conn.commit()
            conn.close()
