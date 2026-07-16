"""
Raw Data Archiver — permanent append-only archive of every collected item.

The working SQLite DB has 90-day retention (items get cleaned up).
The archive is SEPARATE and NEVER deletes — this builds the historical
dataset that becomes the moat.

Schema:
  raw_archive(
    id TEXT PRIMARY KEY,           -- same as RawItem.id
    source TEXT,
    source_name TEXT,
    title TEXT,
    url TEXT,
    body TEXT,
    author TEXT,
    published_at TEXT,
    collected_at TEXT NOT NULL,    -- when first archived
    archive_date TEXT NOT NULL,    -- YYYY-MM-DD (for monthly partitioning)
    score INTEGER,
    tags TEXT,                     -- JSON array
    raw_metadata TEXT              -- JSON (any extra fields)
  )

  archive_stats(
    archive_date TEXT PRIMARY KEY,
    items_archived INTEGER,
    sources_active INTEGER,
    archive_size_bytes INTEGER
  )

The archiver runs as a processor AFTER collection but BEFORE other
processors — it archives the raw, unprocessed items.

Monthly compression: items older than 90 days in the archive can be
exported to compressed JSONL files (archive/YYYY-MM.jsonl.gz) and
removed from the active archive table to keep it fast.

Usage:
    archiver = RawDataArchiver(db_path)
    archiver.archive_items(raw_items)
    stats = archiver.get_stats()
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from core.logger import get_logger
from core.models import RawItem


_ARCHIVE_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_archive (
    id TEXT PRIMARY KEY,
    source TEXT,
    source_name TEXT,
    title TEXT,
    url TEXT,
    body TEXT,
    author TEXT,
    published_at TEXT,
    collected_at TEXT NOT NULL,
    archive_date TEXT NOT NULL,
    score INTEGER,
    tags TEXT,
    raw_metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_archive_source ON raw_archive(source);
CREATE INDEX IF NOT EXISTS idx_archive_date ON raw_archive(archive_date);
CREATE INDEX IF NOT EXISTS idx_archive_collected ON raw_archive(collected_at);
CREATE INDEX IF NOT EXISTS idx_archive_source_name ON raw_archive(source_name);

CREATE TABLE IF NOT EXISTS archive_stats (
    archive_date TEXT PRIMARY KEY,
    items_archived INTEGER DEFAULT 0,
    sources_active INTEGER DEFAULT 0,
    archive_size_bytes INTEGER DEFAULT 0
);
"""


class RawDataArchiver:
    """Permanent append-only archive of raw collected items.

    The archive is the moat — every item ever collected, never deleted.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._logger = get_logger("raw_archiver")

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.executescript(_ARCHIVE_SCHEMA)
            conn.commit()
            conn.close()

    def archive_items(self, items: list[RawItem]) -> int:
        """Archive a list of raw items. Returns count of newly archived items.

        Idempotent: if an item with the same ID is already archived, it's skipped.
        """
        if not items:
            return 0

        now = datetime.now(timezone.utc)
        archive_date = now.strftime("%Y-%m-%d")
        archived = 0

        with self._lock:
            conn = sqlite3.connect(self._db_path)
            for item in items:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO raw_archive
                           (id, source, source_name, title, url, body, author,
                            published_at, collected_at, archive_date, score, tags, raw_metadata)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            item.id,
                            item.source,
                            item.source_name,
                            item.title,
                            item.url,
                            item.body,
                            item.author,
                            item.published_at,
                            item.collected_at or now.isoformat(),
                            archive_date,
                            item.score,
                            json.dumps(item.tags or []),
                            json.dumps({}),
                        ),
                    )
                    if conn.total_changes > 0:
                        archived += 1
                except Exception as e:
                    self._logger.warning(f"Failed to archive item {item.id}: {e}")

            conn.commit()

            # Update daily stats
            self._update_stats(conn, archive_date, archived, items)

            conn.close()

        self._logger.info(f"Archived {archived}/{len(items)} items (date: {archive_date})")
        return archived

    def _update_stats(self, conn: sqlite3.Connection, archive_date: str, new_items: int, items: list[RawItem]) -> None:
        """Update daily archive stats."""
        # Count distinct sources in this batch
        sources_today = {item.source for item in items if item.source}

        # Get existing stats for today
        row = conn.execute(
            "SELECT items_archived, sources_active FROM archive_stats WHERE archive_date = ?",
            (archive_date,)
        ).fetchone()

        if row:
            total_items = row[0] + new_items
            # sources_active = max of existing and new
            total_sources = max(row[1], len(sources_today))
            conn.execute(
                """UPDATE archive_stats
                   SET items_archived = ?, sources_active = ?
                   WHERE archive_date = ?""",
                (total_items, total_sources, archive_date),
            )
        else:
            conn.execute(
                """INSERT INTO archive_stats (archive_date, items_archived, sources_active, archive_size_bytes)
                   VALUES (?, ?, ?, 0)""",
                (archive_date, new_items, len(sources_today)),
            )

    def get_stats(self) -> dict:
        """Get aggregate archive stats."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row

            total_items = conn.execute("SELECT COUNT(*) AS c FROM raw_archive").fetchone()["c"]

            # Distinct sources
            sources_row = conn.execute(
                "SELECT COUNT(DISTINCT source) AS c FROM raw_archive"
            ).fetchone()
            total_sources = sources_row["c"]

            # Distinct source_names
            source_names_row = conn.execute(
                "SELECT COUNT(DISTINCT source_name) AS c FROM raw_archive"
            ).fetchone()
            total_source_names = source_names_row["c"]

            # Date range
            date_range = conn.execute(
                "SELECT MIN(archive_date) AS min_d, MAX(archive_date) AS max_d FROM raw_archive"
            ).fetchone()

            # Items per source (top 10)
            top_sources = conn.execute(
                """SELECT source, COUNT(*) AS c
                   FROM raw_archive
                   GROUP BY source
                   ORDER BY c DESC
                   LIMIT 10"""
            ).fetchall()

            # Daily stats (last 7 days)
            daily_stats = conn.execute(
                """SELECT archive_date, items_archived, sources_active
                   FROM archive_stats
                   ORDER BY archive_date DESC
                   LIMIT 7"""
            ).fetchall()

            # Items per country (if tags contain country info — best-effort)
            # For now, just count by source type
            by_source_type = conn.execute(
                """SELECT source, COUNT(*) AS c
                   FROM raw_archive
                   GROUP BY source
                   ORDER BY c DESC"""
            ).fetchall()

            conn.close()

        return {
            "total_items_archived": total_items,
            "total_distinct_sources": total_sources,
            "total_distinct_source_names": total_source_names,
            "earliest_archive_date": date_range["min_d"],
            "latest_archive_date": date_range["max_d"],
            "top_sources": [{"source": r["source"], "count": r["c"]} for r in top_sources],
            "daily_stats_last_7": [
                {"date": r["archive_date"], "items": r["items_archived"], "sources": r["sources_active"]}
                for r in daily_stats
            ],
            "by_source_type": [{"source": r["source"], "count": r["c"]} for r in by_source_type],
        }

    def get_items_count_by_source(self, source: str) -> int:
        """Count archived items from a specific source."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM raw_archive WHERE source = ?",
                (source,)
            ).fetchone()
            conn.close()
        return row["c"] if row else 0

    def get_date_range_count(self, start_date: str, end_date: str) -> int:
        """Count items archived between two dates (inclusive)."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            row = conn.execute(
                """SELECT COUNT(*) AS c FROM raw_archive
                   WHERE archive_date >= ? AND archive_date <= ?""",
                (start_date, end_date)
            ).fetchone()
            conn.close()
        return row["c"]
