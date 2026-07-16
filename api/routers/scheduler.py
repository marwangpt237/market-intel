"""Scheduler endpoints — job management + run history."""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.config import config

router = APIRouter()


def _get_scheduler():
    from scheduler.engine import get_scheduler
    return get_scheduler()


class JobConfig(BaseModel):
    """Configuration for a scheduled job."""
    id: str = Field(..., description="Unique job ID")
    name: str = Field(..., description="Human-readable name")
    profile: str = Field(default="default", description="Pipeline profile")
    cron: str = Field(..., description="Cron expression (5 fields: minute hour day month day_of_week)")
    enabled: bool = Field(default=True)
    max_retries: int = Field(default=2, ge=0, le=10)
    retry_backoff_seconds: int = Field(default=60, ge=1, le=3600)


class TriggerRunRequest(BaseModel):
    profile: str = Field(default="default")
    job_id: str | None = Field(default=None)


# ─── Scheduler control ─────────────────────────────────────────────────

@router.post("/scheduler/start")
async def start_scheduler():
    """Start the scheduler (registers default jobs)."""
    sched = _get_scheduler()
    if sched.is_running():
        return {"status": "already_running", "jobs": sched.list_jobs()}
    sched.start()
    return {"status": "started", "jobs": sched.list_jobs()}


@router.post("/scheduler/stop")
async def stop_scheduler():
    """Stop the scheduler."""
    sched = _get_scheduler()
    if not sched.is_running():
        return {"status": "not_running"}
    sched.shutdown(wait=False)
    return {"status": "stopped"}


@router.get("/scheduler/status")
async def scheduler_status():
    """Get scheduler status."""
    sched = _get_scheduler()
    return {
        "running": sched.is_running(),
        "jobs": sched.list_jobs() if sched.is_running() else [],
        "active_runs": sched.get_active_runs(),
    }


# ─── Job management ────────────────────────────────────────────────────

@router.get("/scheduler/jobs")
async def list_jobs():
    """List all scheduled jobs."""
    sched = _get_scheduler()
    return {"jobs": sched.list_jobs()}


@router.post("/scheduler/jobs")
async def add_job(job: JobConfig):
    """Add a new scheduled job."""
    sched = _get_scheduler()
    if not sched.is_running():
        raise HTTPException(status_code=400, detail="Scheduler not running. Start it first.")
    try:
        job_id = sched.add_job(job.model_dump())
        return {"status": "added", "job_id": job_id, "job": job.model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/scheduler/jobs/{job_id}")
async def remove_job(job_id: str):
    """Remove a scheduled job."""
    sched = _get_scheduler()
    removed = sched.remove_job(job_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return {"status": "removed", "job_id": job_id}


@router.post("/scheduler/jobs/{job_id}/pause")
async def pause_job(job_id: str):
    """Pause a scheduled job."""
    sched = _get_scheduler()
    if not sched.pause_job(job_id):
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return {"status": "paused", "job_id": job_id}


@router.post("/scheduler/jobs/{job_id}/resume")
async def resume_job(job_id: str):
    """Resume a paused job."""
    sched = _get_scheduler()
    if not sched.resume_job(job_id):
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return {"status": "resumed", "job_id": job_id}


# ─── Manual runs ───────────────────────────────────────────────────────

@router.post("/scheduler/runs/trigger")
async def trigger_run(req: TriggerRunRequest):
    """Trigger a manual run immediately. Returns run_id."""
    sched = _get_scheduler()
    run_id = sched.trigger_run_now(profile=req.profile, job_id=req.job_id)
    return {
        "run_id": run_id,
        "profile": req.profile,
        "status": "started",
        "message": f"Run triggered. Check status at /api/v1/scheduler/runs/{run_id}",
    }


@router.get("/scheduler/runs")
async def list_runs(
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List runs (active + historical)."""
    sched = _get_scheduler()
    active = sched.get_active_runs()
    history = sched.history.get_recent_runs(limit=limit, status=status)
    return {
        "active": active,
        "history": history,
        "stats": sched.history.get_stats(),
    }


@router.get("/scheduler/runs/{run_id}")
async def get_run(run_id: str):
    """Get status of a specific run."""
    sched = _get_scheduler()
    run = sched.get_run_status(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run


@router.delete("/scheduler/runs/{run_id}")
async def cancel_run(run_id: str):
    """Cancel an active run (best-effort)."""
    sched = _get_scheduler()
    cancelled = sched.cancel_run(run_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail=f"Active run '{run_id}' not found")
    return {"run_id": run_id, "status": "cancelling", "message": "Cancellation requested"}


@router.get("/scheduler/runs/stats/summary")
async def get_run_stats():
    """Get aggregate run stats."""
    sched = _get_scheduler()
    return sched.history.get_stats()
