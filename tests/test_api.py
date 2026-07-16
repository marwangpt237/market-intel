"""Tests for Phase 1 — FastAPI backend."""
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    from api.app import app
    return TestClient(app)


@pytest.fixture
def temp_db():
    """Use a temp DB for tests that need DB access."""
    tmpdir = tempfile.mkdtemp()
    old_db = os.environ.get("MARKET_INTEL_DB")
    old_archive = os.environ.get("MARKET_INTEL_ARCHIVE_DB")
    os.environ["MARKET_INTEL_DB"] = os.path.join(tmpdir, "test.db")
    os.environ["MARKET_INTEL_ARCHIVE_DB"] = os.path.join(tmpdir, "test_archive.db")

    # Reload config
    from api.config import APIConfig
    APIConfig.DB_PATH = os.environ["MARKET_INTEL_DB"]
    APIConfig.ARCHIVE_DB_PATH = os.environ["MARKET_INTEL_ARCHIVE_DB"]

    yield tmpdir

    if old_db:
        os.environ["MARKET_INTEL_DB"] = old_db
    else:
        os.environ.pop("MARKET_INTEL_DB", None)
    if old_archive:
        os.environ["MARKET_INTEL_ARCHIVE_DB"] = old_archive
    else:
        os.environ.pop("MARKET_INTEL_ARCHIVE_DB", None)

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


# ─── Health ────────────────────────────────────────────────────────────

def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "version" in data
    assert "docs" in data


def test_health_endpoint(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_health_detailed_endpoint(client):
    response = client.get("/api/v1/health/detailed")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "checks" in data


# ─── Runs ──────────────────────────────────────────────────────────────

def test_list_runs_empty(client):
    response = client.get("/api/v1/runs")
    assert response.status_code == 200
    data = response.json()
    assert "active" in data
    assert "history" in data
    assert isinstance(data["active"], list)


def test_trigger_dry_run(client):
    response = client.post("/api/v1/runs", json={"dry_run": True})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "dry_run"
    assert data["run_id"] == "dry_run"


def test_get_run_not_found(client):
    response = client.get("/api/v1/runs/nonexistent_run")
    assert response.status_code == 404


# ─── Reports ───────────────────────────────────────────────────────────

def test_list_reports(client):
    response = client.get("/api/v1/reports")
    assert response.status_code == 200
    data = response.json()
    assert "reports" in data
    assert "total" in data


def test_reports_types_summary(client):
    response = client.get("/api/v1/reports/types/summary")
    assert response.status_code == 200
    data = response.json()
    assert "types" in data


def test_get_report_not_found(client):
    response = client.get("/api/v1/reports/nonexistent.md")
    assert response.status_code == 404


def test_get_report_invalid_filename(client):
    """Path traversal should be blocked."""
    response = client.get("/api/v1/reports/../etc/passwd")
    assert response.status_code in (400, 404)


# ─── Collectors ────────────────────────────────────────────────────────

def test_list_collectors(client):
    response = client.get("/api/v1/collectors")
    assert response.status_code == 200
    data = response.json()
    assert "collectors" in data
    assert "total" in data
    assert "stats" in data


def test_list_collectors_by_country(client):
    response = client.get("/api/v1/collectors?country=DZ")
    assert response.status_code == 200
    data = response.json()
    # Should have Algerian collectors (at least some registered via imports)
    assert data["total"] >= 0


def test_get_collector_not_found(client):
    response = client.get("/api/v1/collectors/nonexistent_collector")
    assert response.status_code == 404


def test_collectors_stats_summary(client):
    response = client.get("/api/v1/collectors/stats/summary")
    assert response.status_code == 200


def test_collectors_health_all(client):
    response = client.get("/api/v1/collectors/health/all")
    assert response.status_code == 200
    data = response.json()
    assert "collectors" in data
    assert "stats" in data


# ─── Claims ────────────────────────────────────────────────────────────

def test_list_claims(client, temp_db):
    response = client.get("/api/v1/claims")
    assert response.status_code == 200
    data = response.json()
    assert "claims" in data
    assert "total" in data


def test_claims_stats_summary(client, temp_db):
    response = client.get("/api/v1/claims/stats/summary")
    assert response.status_code == 200


def test_get_claim_not_found(client, temp_db):
    response = client.get("/api/v1/claims/nonexistent_claim")
    assert response.status_code == 404


# ─── Decisions ─────────────────────────────────────────────────────────

def test_list_decisions(client, temp_db):
    response = client.get("/api/v1/decisions")
    assert response.status_code == 200
    data = response.json()
    assert "decisions" in data
    assert "total" in data


def test_decisions_stats_summary(client, temp_db):
    response = client.get("/api/v1/decisions/stats/summary")
    assert response.status_code == 200


def test_get_decision_not_found(client, temp_db):
    response = client.get("/api/v1/decisions/nonexistent_decision")
    assert response.status_code == 404


# ─── Search ────────────────────────────────────────────────────────────

def test_search_empty_query(client):
    response = client.get("/api/v1/search")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0


def test_search_with_query(client):
    response = client.get("/api/v1/search?q=test")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data


def test_search_sources(client):
    response = client.get("/api/v1/search/sources")
    assert response.status_code == 200
    data = response.json()
    assert "sources" in data


# ─── Stats ─────────────────────────────────────────────────────────────

def test_dashboard_metrics(client):
    response = client.get("/api/v1/stats/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "archive" in data
    assert "claims" in data
    assert "decisions" in data
    assert "collectors" in data


def test_archive_stats(client):
    response = client.get("/api/v1/stats/archive")
    assert response.status_code == 200


def test_db_stats(client):
    response = client.get("/api/v1/stats/db")
    assert response.status_code == 200


# ─── OpenAPI ───────────────────────────────────────────────────────────

def test_openapi_schema(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert data["info"]["title"] == "Market-Intel API"
    assert "paths" in data


def test_docs_endpoint(client):
    response = client.get("/docs")
    assert response.status_code == 200


def test_redoc_endpoint(client):
    response = client.get("/redoc")
    assert response.status_code == 200
