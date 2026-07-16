"""Tests for Phase 2 — APScheduler."""
import sys, os, tempfile, shutil, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.app import app
    return TestClient(app)


@pytest.fixture
def temp_db():
    tmpdir = tempfile.mkdtemp()
    old_db = os.environ.get("MARKET_INTEL_DB")
    os.environ["MARKET_INTEL_DB"] = os.path.join(tmpdir, "test.db")
    from api.config import APIConfig
    APIConfig.DB_PATH = os.environ["MARKET_INTEL_DB"]
    yield tmpdir
    if old_db:
        os.environ["MARKET_INTEL_DB"] = old_db
    else:
        os.environ.pop("MARKET_INTEL_DB", None)
    shutil.rmtree(tmpdir, ignore_errors=True)


# ─── Run History Store ─────────────────────────────────────────────────

def test_run_history_record_and_get():
    from scheduler.run_history import RunHistoryStore
    tmpdir = tempfile.mkdtemp()
    try:
        store = RunHistoryStore(os.path.join(tmpdir, "test.db"))
        store.record_start("run_test1", "default", triggered_by="manual")
        store.record_completion("run_test1", "completed", summary={"total_items": 42})

        run = store.get_run("run_test1")
        assert run is not None
        assert run["status"] == "completed"
        assert run["items_processed"] == 42
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_run_history_stats():
    from scheduler.run_history import RunHistoryStore
    tmpdir = tempfile.mkdtemp()
    try:
        store = RunHistoryStore(os.path.join(tmpdir, "test.db"))
        for i in range(3):
            store.record_start(f"run_{i}", "default")
            store.record_completion(f"run_{i}", "completed" if i < 2 else "failed")

        stats = store.get_stats()
        assert stats["total_runs"] == 3
        assert stats["by_status"]["completed"] == 2
        assert stats["by_status"]["failed"] == 1
        assert stats["success_rate"] > 0.6
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_run_history_recent_runs():
    from scheduler.run_history import RunHistoryStore
    tmpdir = tempfile.mkdtemp()
    try:
        store = RunHistoryStore(os.path.join(tmpdir, "test.db"))
        for i in range(5):
            store.record_start(f"run_{i}", "default")
            store.record_completion(f"run_{i}", "completed")

        recent = store.get_recent_runs(limit=3)
        assert len(recent) == 3
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ─── Scheduler Engine ──────────────────────────────────────────────────

def test_scheduler_singleton():
    from scheduler.engine import MarketIntelScheduler
    s1 = MarketIntelScheduler()
    s2 = MarketIntelScheduler()
    assert s1 is s2


def test_scheduler_start_stop():
    from scheduler.engine import get_scheduler
    sched = get_scheduler()
    # Reset singleton state for test
    sched._scheduler = None

    sched.start()
    assert sched.is_running()

    sched.shutdown(wait=False)
    assert not sched.is_running()


def test_scheduler_add_remove_job():
    from scheduler.engine import get_scheduler
    sched = get_scheduler()
    sched._scheduler = None
    sched.start()

    job_id = sched.add_job({
        "id": "test_job_1",
        "name": "Test Job",
        "profile": "default",
        "cron": "0 */6 * * *",
        "enabled": True,
    })
    assert job_id == "test_job_1"

    jobs = sched.list_jobs()
    assert any(j["id"] == "test_job_1" for j in jobs)

    removed = sched.remove_job("test_job_1")
    assert removed is True

    sched.shutdown(wait=False)


def test_scheduler_pause_resume():
    from scheduler.engine import get_scheduler
    sched = get_scheduler()
    sched._scheduler = None
    sched.start()

    sched.add_job({
        "id": "test_pause",
        "name": "Test Pause",
        "profile": "default",
        "cron": "0 */6 * * *",
    })

    assert sched.pause_job("test_pause") is True
    assert sched.resume_job("test_pause") is True

    sched.shutdown(wait=False)


# ─── API endpoints ─────────────────────────────────────────────────────

def test_scheduler_status_endpoint(client):
    response = client.get("/api/v1/scheduler/status")
    assert response.status_code == 200
    data = response.json()
    assert "running" in data
    assert "jobs" in data
    assert "active_runs" in data


def test_scheduler_start_endpoint(client):
    response = client.post("/api/v1/scheduler/start")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("started", "already_running")


def test_scheduler_list_jobs(client):
    response = client.get("/api/v1/scheduler/jobs")
    assert response.status_code == 200
    data = response.json()
    assert "jobs" in data


def test_scheduler_add_job_endpoint(client):
    # First ensure scheduler is started
    client.post("/api/v1/scheduler/start")

    response = client.post("/api/v1/scheduler/jobs", json={
        "id": "test_api_job",
        "name": "Test API Job",
        "profile": "default",
        "cron": "0 */6 * * *",
        "enabled": True,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "added"

    # Cleanup
    client.delete("/api/v1/scheduler/jobs/test_api_job")


def test_scheduler_remove_job_not_found(client):
    response = client.delete("/api/v1/scheduler/jobs/nonexistent")
    assert response.status_code == 404


def test_scheduler_runs_list(client):
    response = client.get("/api/v1/scheduler/runs")
    assert response.status_code == 200
    data = response.json()
    assert "active" in data
    assert "history" in data
    assert "stats" in data


def test_scheduler_runs_stats(client):
    response = client.get("/api/v1/scheduler/runs/stats/summary")
    assert response.status_code == 200


def test_scheduler_get_run_not_found(client):
    response = client.get("/api/v1/scheduler/runs/nonexistent")
    assert response.status_code == 404
