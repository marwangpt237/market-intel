"""
Claim Store — SQLite persistence for claims, evidence, and version history.

Schema:
  claims(
    id TEXT PRIMARY KEY,
    entity TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    value TEXT NOT NULL,           -- JSON-encoded
    value_unit TEXT,
    sources TEXT,                  -- JSON array
    evidence_count INTEGER,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    last_verified TEXT,
    supporting_evidence TEXT,      -- JSON array
    contradicting_evidence TEXT,   -- JSON array
    confidence_score REAL,
    validation_status TEXT,
    expiration_date TEXT,
    updated_at TEXT NOT NULL
  )

  claim_evidence(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_type TEXT,
    source_reliability REAL,
    value TEXT,
    item_id TEXT,
    item_url TEXT,
    item_title TEXT,
    collected_at TEXT,
    supports INTEGER,              -- 1 or 0
    confidence REAL,
    added_at TEXT NOT NULL,
    FOREIGN KEY (claim_id) REFERENCES claims(id)
  )

  claim_version_history(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT,
    old_confidence REAL,
    new_confidence REAL,
    reason TEXT,
    FOREIGN KEY (claim_id) REFERENCES claims(id)
  )

Indexes:
  claims(entity, claim_type)
  claims(validation_status)
  claims(confidence_score)
  claims(last_seen)
  claim_evidence(claim_id)
  claim_version_history(claim_id)
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from core.logger import get_logger
from validation.models import Claim, Evidence, ValidationStatus


_SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    entity TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    value TEXT NOT NULL,
    value_unit TEXT,
    sources TEXT,
    evidence_count INTEGER DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    last_verified TEXT,
    supporting_evidence TEXT,
    contradicting_evidence TEXT,
    confidence_score REAL DEFAULT 0.0,
    validation_status TEXT DEFAULT 'UNKNOWN',
    expiration_date TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claims_entity_type ON claims(entity, claim_type);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(validation_status);
CREATE INDEX IF NOT EXISTS idx_claims_confidence ON claims(confidence_score);
CREATE INDEX IF NOT EXISTS idx_claims_last_seen ON claims(last_seen);

CREATE TABLE IF NOT EXISTS claim_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_type TEXT,
    source_reliability REAL,
    value TEXT,
    item_id TEXT,
    item_url TEXT,
    item_title TEXT,
    collected_at TEXT,
    supports INTEGER DEFAULT 1,
    confidence REAL DEFAULT 1.0,
    added_at TEXT NOT NULL,
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);

CREATE INDEX IF NOT EXISTS idx_evidence_claim_id ON claim_evidence(claim_id);
CREATE INDEX IF NOT EXISTS idx_evidence_source ON claim_evidence(source_id);

CREATE TABLE IF NOT EXISTS claim_version_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT,
    old_confidence REAL,
    new_confidence REAL,
    reason TEXT,
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);

CREATE INDEX IF NOT EXISTS idx_version_claim_id ON claim_version_history(claim_id);
"""


class ClaimStore:
    """SQLite-backed persistence for claims, evidence, and version history."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._logger = get_logger("claim_store")

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.executescript(_SCHEMA)
            conn.commit()
            conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # ─── Claims ────────────────────────────────────────────────────────

    def upsert_claim(self, claim: Claim) -> bool:
        """Insert or update a claim. Returns True if claim is new."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_conn()
            try:
                existing = conn.execute(
                    "SELECT id FROM claims WHERE id = ?", (claim.id,)
                ).fetchone()

                conn.execute(
                    """INSERT INTO claims
                       (id, entity, claim_type, value, value_unit, sources, evidence_count,
                        first_seen, last_seen, last_verified, supporting_evidence,
                        contradicting_evidence, confidence_score, validation_status,
                        expiration_date, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                         entity = excluded.entity,
                         claim_type = excluded.claim_type,
                         value = excluded.value,
                         value_unit = excluded.value_unit,
                         sources = excluded.sources,
                         evidence_count = excluded.evidence_count,
                         last_seen = excluded.last_seen,
                         last_verified = excluded.last_verified,
                         supporting_evidence = excluded.supporting_evidence,
                         contradicting_evidence = excluded.contradicting_evidence,
                         confidence_score = excluded.confidence_score,
                         validation_status = excluded.validation_status,
                         expiration_date = excluded.expiration_date,
                         updated_at = excluded.updated_at""",
                    (
                        claim.id,
                        claim.entity,
                        claim.claim_type,
                        json.dumps(claim.value, default=str),
                        claim.value_unit,
                        json.dumps(claim.sources),
                        claim.evidence_count,
                        claim.first_seen,
                        claim.last_seen,
                        claim.last_verified,
                        json.dumps(claim.supporting_evidence),
                        json.dumps(claim.contradicting_evidence),
                        claim.confidence_score,
                        claim.validation_status,
                        claim.expiration_date,
                        now,
                    ),
                )
                conn.commit()
                return existing is None
            finally:
                conn.close()

    def get_claim(self, claim_id: str) -> Claim | None:
        """Get a single claim by ID."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
            conn.close()

        if not row:
            return None
        return self._row_to_claim(row)

    def get_claims_by_entity(self, entity: str) -> list[Claim]:
        """Get all claims for a given entity."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM claims WHERE entity = ? ORDER BY last_seen DESC",
                (entity,)
            ).fetchall()
            conn.close()
        return [self._row_to_claim(r) for r in rows]

    def get_claims_by_status(self, status: str) -> list[Claim]:
        """Get all claims with a given validation status."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM claims WHERE validation_status = ? ORDER BY confidence_score DESC",
                (status,)
            ).fetchall()
            conn.close()
        return [self._row_to_claim(r) for r in rows]

    def get_all_claims(self, limit: int = 1000) -> list[Claim]:
        """Get all claims, most recent first."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM claims ORDER BY last_seen DESC LIMIT ?", (limit,)
            ).fetchall()
            conn.close()
        return [self._row_to_claim(r) for r in rows]

    def get_stale_claims(self, before_date: str) -> list[Claim]:
        """Get claims whose last_seen is before the given date."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM claims WHERE last_seen < ? AND validation_status NOT IN ('EXPIRED')",
                (before_date,)
            ).fetchall()
            conn.close()
        return [self._row_to_claim(r) for r in rows]

    # ─── Evidence ──────────────────────────────────────────────────────

    def add_evidence(self, claim_id: str, evidence: Evidence) -> None:
        """Add a piece of evidence to a claim."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO claim_evidence
                   (claim_id, source_id, source_type, source_reliability, value,
                    item_id, item_url, item_title, collected_at, supports, confidence, added_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    claim_id,
                    evidence.source_id,
                    evidence.source_type,
                    evidence.source_reliability,
                    json.dumps(evidence.value, default=str),
                    evidence.item_id,
                    evidence.item_url,
                    evidence.item_title,
                    evidence.collected_at,
                    1 if evidence.supports else 0,
                    evidence.confidence,
                    now,
                ),
            )
            conn.commit()
            conn.close()

    def get_evidence_for_claim(self, claim_id: str) -> list[dict]:
        """Get all evidence for a claim."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM claim_evidence WHERE claim_id = ? ORDER BY added_at DESC",
                (claim_id,)
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]

    # ─── Version history ───────────────────────────────────────────────

    def add_version_history(
        self,
        claim_id: str,
        old_status: str | None,
        new_status: str,
        old_confidence: float | None,
        new_confidence: float,
        reason: str,
    ) -> None:
        """Record a status/confidence change in version history."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO claim_version_history
                   (claim_id, timestamp, old_status, new_status, old_confidence, new_confidence, reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (claim_id, now, old_status, new_status, old_confidence, new_confidence, reason),
            )
            conn.commit()
            conn.close()

    def get_version_history(self, claim_id: str) -> list[dict]:
        """Get version history for a claim."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM claim_version_history WHERE claim_id = ? ORDER BY timestamp DESC",
                (claim_id,)
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]

    # ─── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get aggregate stats about the claim store."""
        with self._lock:
            conn = self._get_conn()

            total = conn.execute("SELECT COUNT(*) AS c FROM claims").fetchone()["c"]

            by_status_rows = conn.execute(
                "SELECT validation_status, COUNT(*) AS c FROM claims GROUP BY validation_status"
            ).fetchall()
            by_status = {r["validation_status"]: r["c"] for r in by_status_rows}

            by_type_rows = conn.execute(
                "SELECT claim_type, COUNT(*) AS c FROM claims GROUP BY claim_type"
            ).fetchall()
            by_type = {r["claim_type"]: r["c"] for r in by_type_rows}

            avg_confidence = conn.execute(
                "SELECT AVG(confidence_score) AS avg FROM claims"
            ).fetchone()["avg"] or 0.0

            total_evidence = conn.execute("SELECT COUNT(*) AS c FROM claim_evidence").fetchone()["c"]

            conn.close()

        return {
            "total_claims": total,
            "by_status": by_status,
            "by_type": by_type,
            "avg_confidence": round(avg_confidence, 3),
            "total_evidence_pieces": total_evidence,
        }

    # ─── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _row_to_claim(row: sqlite3.Row) -> Claim:
        """Convert a DB row to a Claim object."""
        return Claim(
            id=row["id"],
            entity=row["entity"],
            claim_type=row["claim_type"],
            value=json.loads(row["value"]),
            value_unit=row["value_unit"],
            sources=json.loads(row["sources"] or "[]"),
            evidence_count=row["evidence_count"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            last_verified=row["last_verified"],
            supporting_evidence=json.loads(row["supporting_evidence"] or "[]"),
            contradicting_evidence=json.loads(row["contradicting_evidence"] or "[]"),
            confidence_score=row["confidence_score"],
            validation_status=row["validation_status"],
            expiration_date=row["expiration_date"],
        )
