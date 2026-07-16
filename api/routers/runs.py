"""Run endpoints — manual triggers + run history."""
from __future__ import annotations
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from api.config import config

router = APIRouter()

# In-memory run tracking (Phase 2 will move to APScheduler + DB)
_active_runs: dict[str, dict] = {}
_run_history: list[dict] = []
_run_lock = threading.Lock()


class RunRequest(BaseModel):
    """Request to trigger a pipeline run."""
    profile: str | None = Field(default=None, description="Profile to use (default, client_acq, algeria_ecom)")
    dry_run: bool = Field(default=False, description="If true, don't execute — just return what would run")


class RunResponse(BaseModel):
    run_id: str
    status: str
    profile: str
    started_at: str
    message: str


def _resolve_config_path(profile: str | None) -> str:
    """Resolve which config file to use based on profile."""
    if profile == "client_acq":
        return "config.client_acq.yaml"
    elif profile == "algeria_ecom":
        return "config.algeria_ecom.yaml"
    return config.CONFIG_PATH


def _execute_run(run_id: str, profile: str):
    """Execute the pipeline in a background thread."""
    started_at = datetime.now(timezone.utc).isoformat()
    with _run_lock:
        _active_runs[run_id] = {
            "run_id": run_id,
            "profile": profile,
            "status": "running",
            "started_at": started_at,
            "progress": "initializing",
        }

    try:
        # Add project root to path
        project_root = str(Path(__file__).parent.parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        from core.config_loader import load_config
        from workflows.daily_run import DailyRun

        config_path = _resolve_config_path(profile)
        cfg = load_config(config_path)

        # Update progress
        with _run_lock:
            _active_runs[run_id]["progress"] = "collecting"

        workflow = DailyRun(cfg)
        summary = workflow.run()

        completed_at = datetime.now(timezone.utc).isoformat()
        with _run_lock:
            _active_runs[run_id]["status"] = summary.get("status", "unknown")
            _active_runs[run_id]["completed_at"] = completed_at
            _active_runs[run_id]["summary"] = summary
            _active_runs[run_id]["progress"] = "complete"

            # Move to history
            _run_history.append(_active_runs[run_id].copy())
            if len(_run_history) > 50:
                _run_history.pop(0)
            del _active_runs[run_id]

    except Exception as e:
        import traceback
        error = str(e)
        trace = traceback.format_exc()
        with _run_lock:
            _active_runs[run_id]["status"] = "failed"
            _active_runs[run_id]["error"] = error
            _active_runs[run_id]["traceback"] = trace
            _active_runs[run_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
            _run_history.append(_active_runs[run_id].copy())
            if len(_run_history) > 50:
                _run_history.pop(0)
            if run_id in _active_runs:
                del _active_runs[run_id]


@router.post("/runs", response_model=RunResponse)
async def trigger_run(req: RunRequest, background_tasks: BackgroundTasks):
    """Trigger a manual pipeline run.

    Returns immediately with a run_id. Check status via GET /runs/{run_id}.
    Only one run can be active at a time (configurable in APIConfig).
    """
    # Check concurrent run limit
    with _run_lock:
        if len(_active_runs) >= config.MAX_CONCURRENT_RUNS:
            raise HTTPException(
                status_code=409,
                detail=f"A run is already in progress. Active runs: {list(_active_runs.keys())}",
            )

    if req.dry_run:
        config_path = _resolve_config_path(req.profile)
        return RunResponse(
            run_id="dry_run",
            status="dry_run",
            profile=req.profile or "default",
            started_at=datetime.now(timezone.utc).isoformat(),
            message=f"Would run with config: {config_path}",
        )

    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    profile = req.profile or "default"

    background_tasks.add_task(_execute_run, run_id, profile)

    return RunResponse(
        run_id=run_id,
        status="started",
        profile=profile,
        started_at=datetime.now(timezone.utc).isoformat(),
        message=f"Run started with profile '{profile}'. Check status at /api/v1/runs/{run_id}",
    )


@router.get("/runs")
async def list_runs():
    """List all runs (active + recent history)."""
    with _run_lock:
        active = list(_active_runs.values())
        history = list(_run_history)
    return {
        "active": active,
        "history": history[-20:],  # last 20
        "total_history": len(history),
    }


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Get status of a specific run."""
    with _run_lock:
        if run_id in _active_runs:
            return _active_runs[run_id]
        for run in reversed(_run_history):
            if run.get("run_id") == run_id:
                return run
    raise HTTPException(status_code=404, detail=f"Run {run_id} not found")


@router.delete("/runs/{run_id}")
async def cancel_run(run_id: str):
    """Cancel an active run (best-effort — Python threads can't be killed).

    Marks the run as 'cancelling' — the actual collection can't be
    interrupted, but new processors will be skipped.
    """
    with _run_lock:
        if run_id in _active_runs:
            _active_runs[run_id]["status"] = "cancelling"
            _active_runs[run_id]["cancel_requested_at"] = datetime.now(timezone.utc).isoformat()
            return {"run_id": run_id, "status": "cancelling", "message": "Cancellation requested"}
    raise HTTPException(status_code=404, detail=f"Active run {run_id} not found")
