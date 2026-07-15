"""
SQLite storage adapter — persists items in a relational database.

Enables:
- Historical trend analysis over 30/90/365 days
- Entity-graph queries (joins between items, entities, pain points)
- Fast aggregation queries (COUNT, GROUP BY)
- Retention management via DELETE with date filters
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from core.logger import get_logger
from storage.base import BaseStorage


_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_name TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    body TEXT,
    author TEXT,
    published_at TEXT,
    collected_at TEXT NOT NULL,
    score INTEGER,
    tags TEXT,           -- JSON array
    metadata TEXT,       -- JSON dict
    sentiment TEXT,
    keywords TEXT,       -- JSON array
    read_time_minutes INTEGER,
    dedup_key TEXT,
    cluster_id INTEGER,
    cluster_label TEXT,
    trend TEXT,
    buying_intent REAL,
    processed_at TEXT,
    run_id TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_source ON items(source);
CREATE INDEX IF NOT EXISTS idx_items_collected ON items(collected_at);
CREATE INDEX IF NOT EXISTS idx_items_dedup ON items(dedup_key);
CREATE INDEX IF NOT EXISTS idx_items_run ON items(run_id);
CREATE INDEX IF NOT EXISTS idx_items_score ON items(score);
CREATE INDEX IF NOT EXISTS idx_items_buying ON items(buying_intent);
"""


class SQLiteStorage(BaseStorage):
    name = "sqlite"

    def __init__(self, config: dict):
        super().__init__(config)
        self._db_path = config.get("path", "data/market_intel.db")
        self._retention_days: int = config.get("retention_days", 365)
        self._lock = threading.Lock()

        # Ensure directory exists
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize schema
        with self._lock:
            conn = self._get_conn()
            conn.executescript(_SCHEMA)
            conn.commit()
            conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def save(self, items: list[dict], run_id: str) -> str:
        """Save items to SQLite. Returns the db path."""
        with self._lock:
            conn = self._get_conn()
            saved = 0

            for item in items:
                try:
                    conn.execute(
                        """INSERT OR REPLACE INTO items
                           (id, source, source_name, title, url, body, author,
                            published_at, collected_at, score, tags, metadata,
                            sentiment, keywords, read_time_minutes, dedup_key,
                            cluster_id, cluster_label, trend, buying_intent,
                            processed_at, run_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            item.get("id", ""),
                            item.get("source", ""),
                            item.get("source_name", ""),
                            item.get("title", ""),
                            item.get("url", ""),
                            item.get("body", ""),
                            item.get("author", ""),
                            item.get("published_at"),
                            item.get("collected_at", ""),
                            item.get("score"),
                            json.dumps(item.get("tags", [])),
                            json.dumps(item.get("metadata", {})),
                            item.get("sentiment", "neutral"),
                            json.dumps(item.get("keywords", [])),
                            item.get("read_time_minutes", 0),
                            item.get("dedup_key", ""),
                            item.get("cluster_id"),
                            item.get("cluster_label"),
                            item.get("trend", "stable"),
                            item.get("buying_intent", 0.0),
                            item.get("processed_at", ""),
                            run_id,
                        )
                    )
                    saved += 1
                except Exception as e:
                    self._logger.warning(f"Failed to save item {item.get('id', '?')}: {e}")

            conn.commit()
            conn.close()

        self._logger.info(f"Saved {saved} items to SQLite ({self._db_path})", extra={"saved": saved, "run_id": run_id})

        # Cleanup old data
        self._cleanup_old()

        return self._db_path

    def load_recent(self, days: int = 7) -> list[dict]:
        """Load items from the last N days."""
        with self._lock:
            conn = self._get_conn()
            cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)

            rows = conn.execute(
                """SELECT * FROM items
                   WHERE strftime('%s', collected_at) > ?
                   ORDER BY collected_at DESC""",
                (str(cutoff),)
            ).fetchall()
            conn.close()

        return [self._row_to_dict(row) for row in rows]

    def load_keyword_history(self, days: int = 30) -> dict[str, int]:
        """Load keyword frequency counts from the last N days.
        Returns dict: {keyword: total_count}
        """
        with self._lock:
            conn = self._get_conn()
            cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)

            rows = conn.execute(
                "SELECT keywords FROM items WHERE strftime('%s', collected_at) > ?",
                (str(cutoff),)
            ).fetchall()
            conn.close()

        counts: dict[str, int] = {}
        for row in rows:
            try:
                keywords = json.loads(row["keywords"] or "[]")
                for kw in keywords:
                    counts[kw] = counts.get(kw, 0) + 1
            except Exception:
                continue

        return counts

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """Execute a raw SQL query and return results as dicts."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(sql, params).fetchall()
            conn.close()
        return [self._row_to_dict(row) for row in rows]

    def _cleanup_old(self) -> None:
        """Delete items older than retention_days."""
        cutoff = datetime.now(timezone.utc).timestamp() - (self._retention_days * 86400)
        with self._lock:
            conn = self._get_conn()
            cur = conn.execute(
                "DELETE FROM items WHERE strftime('%s', collected_at) < ?",
                (str(cutoff),)
            )
            deleted = cur.rowcount
            conn.commit()
            conn.close()

        if deleted > 0:
            self._logger.info(f"Cleaned up {deleted} old items", extra={"deleted": deleted})

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        # Parse JSON fields
        for field in ("tags", "keywords"):
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except Exception:
                    d[field] = []
        if d.get("metadata"):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except Exception:
                d["metadata"] = {}
        return d
