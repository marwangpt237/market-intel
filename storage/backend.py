"""
Storage Abstraction Layer — interchangeable SQLite + PostgreSQL backends.

Provides a unified DatabaseBackend interface so all storage code can work
with either SQLite (development) or PostgreSQL (production) without changes.

Usage:
    from storage.backend import get_backend
    backend = get_backend()  # auto-detects from MARKET_INTEL_DB_URL env
    backend.execute("SELECT * FROM items WHERE id = ?", (item_id,))
    backend.executemany("INSERT INTO ... VALUES (?, ?)", items)
    backend.executescript(schema_sql)

Detection:
  - If MARKET_INTEL_DB_URL starts with "postgresql://" → PostgreSQL
  - If MARKET_INTEL_DB_URL starts with "sqlite://" or not set → SQLite
  - Falls back to MARKET_INTEL_DB path for SQLite

Both backends use ? as placeholder (psycopg2 with mogrify translates to %s internally).
"""
from __future__ import annotations

import os
import threading
from typing import Any, Sequence
from core.logger import get_logger


class DatabaseBackend:
    """Abstract database backend interface."""

    def execute(self, sql: str, params: Sequence | None = None) -> Any:
        """Execute a single SQL statement. Returns cursor."""
        raise NotImplementedError

    def executemany(self, sql: str, params_seq: Sequence[Sequence]) -> None:
        """Execute SQL against multiple parameter sets."""
        raise NotImplementedError

    def executescript(self, sql: str) -> None:
        """Execute a script of multiple SQL statements."""
        raise NotImplementedError

    def fetchone(self, sql: str, params: Sequence | None = None) -> dict | None:
        """Execute + fetch one row as dict."""
        raise NotImplementedError

    def fetchall(self, sql: str, params: Sequence | None = None) -> list[dict]:
        """Execute + fetch all rows as dicts."""
        raise NotImplementedError

    def commit(self) -> None:
        """Commit current transaction."""
        raise NotImplementedError

    def close(self) -> None:
        """Close the connection."""
        raise NotImplementedError

    @property
    def backend_type(self) -> str:
        """Return 'sqlite' or 'postgresql'."""
        raise NotImplementedError


class SQLiteBackend(DatabaseBackend):
    """SQLite backend (default for development)."""

    def __init__(self, db_path: str):
        import sqlite3
        self._db_path = db_path
        self._lock = threading.Lock()
        self._logger = get_logger("backend.sqlite")
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    @property
    def backend_type(self) -> str:
        return "sqlite"

    def execute(self, sql: str, params: Sequence | None = None) -> Any:
        with self._lock:
            cur = self._conn.execute(sql, params or [])
            self._conn.commit()
            return cur

    def executemany(self, sql: str, params_seq: Sequence[Sequence]) -> None:
        with self._lock:
            self._conn.executemany(sql, params_seq)
            self._conn.commit()

    def executescript(self, sql: str) -> None:
        with self._lock:
            self._conn.executescript(sql)
            self._conn.commit()

    def fetchone(self, sql: str, params: Sequence | None = None) -> dict | None:
        with self._lock:
            row = self._conn.execute(sql, params or []).fetchone()
        return dict(row) if row else None

    def fetchall(self, sql: str, params: Sequence | None = None) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(sql, params or []).fetchall()
        return [dict(r) for r in rows]

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class PostgreSQLBackend(DatabaseBackend):
    """PostgreSQL backend (for production).

    Uses psycopg2 with real dict cursor.
    Translates ? placeholders to %s (psycopg2 convention).

    Note: this requires psycopg2-binary to be installed.
    """

    def __init__(self, db_url: str):
        self._db_url = db_url
        self._lock = threading.Lock()
        self._logger = get_logger("backend.postgresql")

        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
        except ImportError:
            raise ImportError(
                "PostgreSQL backend requires psycopg2-binary. Install: pip install psycopg2-binary"
            )

        self._psycopg2 = psycopg2
        self._conn = psycopg2.connect(db_url)
        self._conn.autocommit = False
        self._RealDictCursor = RealDictCursor

    @property
    def backend_type(self) -> str:
        return "postgresql"

    @staticmethod
    def _translate_sql(sql: str) -> str:
        """Translate ? placeholders to %s for psycopg2."""
        # Simple replacement — works for standard SQL with ? params
        # Note: this doesn't handle ? inside string literals, but our SQL
        # doesn't have that pattern.
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: Sequence | None = None) -> Any:
        sql = self._translate_sql(sql)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params or [])
            self._conn.commit()
            return cur

    def executemany(self, sql: str, params_seq: Sequence[Sequence]) -> None:
        sql = self._translate_sql(sql)
        with self._lock:
            cur = self._conn.cursor()
            cur.executemany(sql, params_seq)
            self._conn.commit()

    def executescript(self, sql: str) -> None:
        """PostgreSQL doesn't have executescript — split on semicolons."""
        with self._lock:
            cur = self._conn.cursor()
            # Split on semicolons (simple — doesn't handle semicolons in strings)
            statements = [s.strip() for s in sql.split(";") if s.strip()]
            for stmt in statements:
                try:
                    cur.execute(stmt)
                except Exception as e:
                    self._logger.warning(f"Statement failed (continuing): {e}")
            self._conn.commit()

    def fetchone(self, sql: str, params: Sequence | None = None) -> dict | None:
        sql = self._translate_sql(sql)
        with self._lock:
            cur = self._conn.cursor(cursor_factory=self._RealDictCursor)
            cur.execute(sql, params or [])
            row = cur.fetchone()
            self._conn.commit()
        return dict(row) if row else None

    def fetchall(self, sql: str, params: Sequence | None = None) -> list[dict]:
        sql = self._translate_sql(sql)
        with self._lock:
            cur = self._conn.cursor(cursor_factory=self._RealDictCursor)
            cur.execute(sql, params or [])
            rows = cur.fetchall()
            self._conn.commit()
        return [dict(r) for r in rows]

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ─── Factory ───────────────────────────────────────────────────────────

_backend: DatabaseBackend | None = None
_backend_lock = threading.Lock()


def get_backend(db_url: str | None = None) -> DatabaseBackend:
    """Get or create the database backend.

    Detection:
      1. If db_url is provided, use it
      2. Else check MARKET_INTEL_DB_URL env var
      3. Else fall back to MARKET_INTEL_DB path (SQLite)

    Returns:
      SQLiteBackend or PostgreSQLBackend
    """
    global _backend

    with _backend_lock:
        if _backend is not None:
            return _backend

        url = db_url or os.environ.get("MARKET_INTEL_DB_URL", "")

        if url.startswith("postgresql://") or url.startswith("postgres://"):
            _backend = PostgreSQLBackend(url)
        else:
            # SQLite — use MARKET_INTEL_DB path or default
            db_path = os.environ.get(
                "MARKET_INTEL_DB",
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "market_intel.db"),
            )
            _backend = SQLiteBackend(db_path)

        return _backend


def reset_backend() -> None:
    """Reset the backend singleton (for testing)."""
    global _backend
    with _backend_lock:
        if _backend is not None:
            try:
                _backend.close()
            except Exception:
                pass
        _backend = None
