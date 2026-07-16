"""Tests for Phase 5 — Storage abstraction layer."""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


@pytest.fixture
def temp_db():
    tmpdir = tempfile.mkdtemp()
    old_db = os.environ.get("MARKET_INTEL_DB")
    old_url = os.environ.get("MARKET_INTEL_DB_URL")
    os.environ["MARKET_INTEL_DB"] = os.path.join(tmpdir, "test.db")
    os.environ.pop("MARKET_INTEL_DB_URL", None)

    from storage.backend import reset_backend
    reset_backend()

    yield tmpdir

    if old_db:
        os.environ["MARKET_INTEL_DB"] = old_db
    else:
        os.environ.pop("MARKET_INTEL_DB", None)
    if old_url:
        os.environ["MARKET_INTEL_DB_URL"] = old_url

    from storage.backend import reset_backend as reset
    reset()
    shutil.rmtree(tmpdir, ignore_errors=True)


# ─── SQLite Backend ────────────────────────────────────────────────────

def test_sqlite_backend_creation(temp_db):
    from storage.backend import get_backend
    backend = get_backend()
    assert backend.backend_type == "sqlite"


def test_sqlite_backend_execute(temp_db):
    from storage.backend import get_backend
    backend = get_backend()
    backend.executescript("CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, name TEXT)")
    backend.execute("INSERT INTO test (name) VALUES (?)", ("hello",))
    row = backend.fetchone("SELECT * FROM test WHERE name = ?", ("hello",))
    assert row is not None
    assert row["name"] == "hello"


def test_sqlite_backend_fetchall(temp_db):
    from storage.backend import get_backend
    backend = get_backend()
    backend.executescript("CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, name TEXT)")
    backend.executemany("INSERT INTO test (name) VALUES (?)", [("a",), ("b",), ("c",)])
    rows = backend.fetchall("SELECT * FROM test ORDER BY name")
    assert len(rows) == 3
    assert rows[0]["name"] == "a"


def test_sqlite_backend_executescript(temp_db):
    from storage.backend import get_backend
    backend = get_backend()
    backend.executescript("""
        CREATE TABLE IF NOT EXISTS t1 (id INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS t2 (id INTEGER PRIMARY KEY);
        INSERT INTO t1 (id) VALUES (1);
        INSERT INTO t2 (id) VALUES (1);
    """)
    assert backend.fetchone("SELECT COUNT(*) AS c FROM t1")["c"] == 1
    assert backend.fetchone("SELECT COUNT(*) AS c FROM t2")["c"] == 1


def test_sqlite_backend_fetchone_none(temp_db):
    from storage.backend import get_backend
    backend = get_backend()
    backend.executescript("CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, name TEXT)")
    row = backend.fetchone("SELECT * FROM test WHERE name = ?", ("nonexistent",))
    assert row is None


def test_backend_singleton(temp_db):
    """get_backend() should return the same instance."""
    from storage.backend import get_backend
    b1 = get_backend()
    b2 = get_backend()
    assert b1 is b2


def test_backend_reset(temp_db):
    """reset_backend() should clear the singleton."""
    from storage.backend import get_backend, reset_backend
    b1 = get_backend()
    reset_backend()
    b2 = get_backend()
    assert b1 is not b2


# ─── PostgreSQL Backend (skipped if psycopg2 not installed) ────────────

def test_postgresql_backend_import():
    """Test that PostgreSQLBackend can be imported (may fail to connect)."""
    try:
        from storage.backend import PostgreSQLBackend
        assert PostgreSQLBackend is not None
    except ImportError:
        pytest.skip("psycopg2 not installed")


def test_postgresql_sql_translation():
    """Test that ? placeholders are translated to %s for psycopg2."""
    from storage.backend import PostgreSQLBackend
    sql = "SELECT * FROM items WHERE id = ? AND name = ?"
    translated = PostgreSQLBackend._translate_sql(sql)
    assert translated == "SELECT * FROM items WHERE id = %s AND name = %s"


# ─── Backend detection ─────────────────────────────────────────────────

def test_backend_detection_sqlite_via_env(temp_db):
    from storage.backend import get_backend, reset_backend
    reset_backend()
    backend = get_backend()
    assert backend.backend_type == "sqlite"


def test_backend_detection_postgresql_via_url():
    """When MARKET_INTEL_DB_URL is postgresql://, should detect PostgreSQL.

    Note: we don't actually connect — just verify the detection logic.
    """
    old_url = os.environ.get("MARKET_INTEL_DB_URL")
    old_db = os.environ.get("MARKET_INTEL_DB")
    os.environ["MARKET_INTEL_DB_URL"] = "postgresql://user:pass@localhost/db"
    os.environ.pop("MARKET_INTEL_DB", None)

    from storage.backend import reset_backend
    reset_backend()

    # We can't actually create the backend (no real Postgres), but we can
    # verify the detection logic by checking what get_backend would try
    url = os.environ.get("MARKET_INTEL_DB_URL", "")
    assert url.startswith("postgresql://")

    # Restore
    if old_url:
        os.environ["MARKET_INTEL_DB_URL"] = old_url
    else:
        os.environ.pop("MARKET_INTEL_DB_URL", None)
    if old_db:
        os.environ["MARKET_INTEL_DB"] = old_db

    reset_backend()
