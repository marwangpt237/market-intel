"""
Market-Intel Scheduler — APScheduler-based job management.

Replaces GitHub Actions as the primary execution engine.

Features:
  - Job management (add, remove, list, pause, resume)
  - Manual runs (trigger immediately)
  - Scheduled runs (cron-like schedules per profile)
  - Retry policies (exponential backoff)
  - Run history (persisted to SQLite via RunHistoryStore)
  - Run status (queued, running, completed, failed, cancelled)
  - Cancellation (best-effort)
  - Metrics (success rate, avg duration)

The scheduler runs in-process with the FastAPI app. Start it via:
    scheduler.start()  # in app lifespan

Or via the API:
    POST /api/v1/scheduler/start
"""
from __future__ import annotations

import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.jobstores.memory import MemoryJobStore

from core.logger import get_logger
from scheduler.config import DEFAULT_JOBS, DEFAULT_RETRY_POLICY
from scheduler.run_history import RunHistoryStore


class MarketIntelScheduler:
    """APScheduler-based scheduler for Market-Intel pipeline runs.

    Singleton — one instance per process.
    """

    _instance: "MarketIntelScheduler | None" = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self, db_path: str | None = None):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True

        self._logger = get_logger("scheduler")
        self._db_path = db_path or os.environ.get(
            "MARKET_INTEL_DB",
            str(Path(__file__).parent.parent / "data" / "market_intel.db"),
        )
        self._history = RunHistoryStore(self._db_path)
        self._scheduler: BackgroundScheduler | None = None
        self._active_runs: dict[str, dict] = {}  # run_id → run info
        self._cancel_flags: set[str] = set()  # run_ids requested to cancel
        self._run_lock = threading.Lock()

        # Job configs (id → config dict)
        self._job_configs: dict[str, dict] = {}

    @property
    def history(self) -> RunHistoryStore:
        return self._history

    def start(self) -> None:
        """Start the scheduler + register default jobs."""
        if self._scheduler is not None:
            self._logger.warning("Scheduler already started")
            return

        self._scheduler = BackgroundScheduler(
            jobstores={"default": MemoryJobStore()},
            timezone="UTC",
        )
        self._scheduler.start()
        self._logger.info("Scheduler started")

        # Register default jobs
        for job_config in DEFAULT_JOBS:
            if job_config.get("enabled", True):
                self.add_job(job_config)

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the scheduler."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=wait)
            self._scheduler = None
            self._logger.info("Scheduler shut down")

    def is_running(self) -> bool:
        """Check if the scheduler is running."""
        return self._scheduler is not None and self._scheduler.running

    def add_job(self, config: dict) -> str:
        """Add a scheduled job.

        Config:
          id: unique job ID
          name: human-readable name
          profile: pipeline profile (default, client_acq, algeria_ecom)
          cron: cron expression (e.g. "0 */6 * * *")
          enabled: bool
          max_retries: int
          retry_backoff_seconds: int
        """
        if not self._scheduler:
            self._logger.warning("Scheduler not started — cannot add job")
            return ""

        job_id = config.get("id", f"job_{uuid.uuid4().hex[:8]}")
        cron_expr = config.get("cron", "0 */6 * * *")
        name = config.get("name", job_id)

        # Parse cron expression
        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expr} (expected 5 fields)")

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
            timezone="UTC",
        )

        self._scheduler.add_job(
            func=self._execute_scheduled_run,
            trigger=trigger,
            args=[config],
            id=job_id,
            name=name,
            replace_existing=True,
        )

        self._job_configs[job_id] = config
        self._logger.info(f"Job added: {job_id} ({name}) — cron: {cron_expr}")
        return job_id

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job."""
        if not self._scheduler:
            return False
        try:
            self._scheduler.remove_job(job_id)
            self._job_configs.pop(job_id, None)
            self._logger.info(f"Job removed: {job_id}")
            return True
        except Exception as e:
            self._logger.warning(f"Failed to remove job {job_id}: {e}")
            return False

    def pause_job(self, job_id: str) -> bool:
        """Pause a scheduled job."""
        if not self._scheduler:
            return False
        try:
            self._scheduler.pause_job(job_id)
            return True
        except Exception:
            return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job."""
        if not self._scheduler:
            return False
        try:
            self._scheduler.resume_job(job_id)
            return True
        except Exception:
            return False

    def list_jobs(self) -> list[dict]:
        """List all scheduled jobs."""
        if not self._scheduler:
            return []
        jobs = []
        for job in self._scheduler.get_jobs():
            config = self._job_configs.get(job.id, {})
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
                "profile": config.get("profile", "default"),
                "cron": config.get("cron", ""),
                "enabled": not hasattr(job, "paused") or not job.paused,
                "max_retries": config.get("max_retries", 0),
            })
        return jobs

    def trigger_run_now(
        self,
        profile: str = "default",
        job_id: str | None = None,
    ) -> str:
        """Trigger a manual run immediately. Returns run_id."""
        run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        # Start in a background thread (don't block API)
        thread = threading.Thread(
            target=self._execute_run,
            args=(run_id, profile, job_id, "manual"),
            daemon=True,
        )
        thread.start()

        return run_id

    def cancel_run(self, run_id: str) -> bool:
        """Request cancellation of a running job (best-effort)."""
        with self._run_lock:
            if run_id in self._active_runs:
                self._cancel_flags.add(run_id)
                self._active_runs[run_id]["status"] = "cancelling"
                self._logger.info(f"Cancellation requested for run {run_id}")
                return True
        return False

    def get_active_runs(self) -> list[dict]:
        """Get currently-active runs."""
        with self._run_lock:
            return list(self._active_runs.values())

    def get_run_status(self, run_id: str) -> dict | None:
        """Get status of a run (active or historical)."""
        with self._run_lock:
            if run_id in self._active_runs:
                return self._active_runs[run_id]

        # Check history
        return self._history.get_run(run_id)

    def _execute_scheduled_run(self, config: dict) -> None:
        """Execute a scheduled run (called by APScheduler)."""
        profile = config.get("profile", "default")
        job_id = config.get("id")
        run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self._execute_run(run_id, profile, job_id, "scheduled")

    def _execute_run(
        self,
        run_id: str,
        profile: str,
        job_id: str | None,
        triggered_by: str,
    ) -> None:
        """Execute a pipeline run with retry logic."""
        # Record start in history
        self._history.record_start(run_id, profile, job_id, triggered_by)

        # Track in active runs
        with self._run_lock:
            self._active_runs[run_id] = {
                "run_id": run_id,
                "job_id": job_id,
                "profile": profile,
                "status": "running",
                "triggered_by": triggered_by,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "progress": "initializing",
            }

        # Get retry config
        retry_config = DEFAULT_RETRY_POLICY
        if job_id and job_id in self._job_configs:
            retry_config = {
                **DEFAULT_RETRY_POLICY,
                "max_retries": self._job_configs[job_id].get("max_retries", DEFAULT_RETRY_POLICY["max_retries"]),
                "backoff_seconds": self._job_configs[job_id].get("retry_backoff_seconds", DEFAULT_RETRY_POLICY["backoff_seconds"]),
            }

        # Execute with retries
        last_error = None
        for attempt in range(retry_config["max_retries"] + 1):
            try:
                # Check for cancellation
                if run_id in self._cancel_flags:
                    self._finish_run(run_id, "cancelled")
                    return

                # Execute the pipeline
                summary = self._run_pipeline(run_id, profile)

                # Check for cancellation again
                if run_id in self._cancel_flags:
                    self._finish_run(run_id, "cancelled")
                    return

                # Success
                self._finish_run(run_id, "completed", summary=summary)
                return

            except Exception as e:
                import traceback
                last_error = str(e)
                last_traceback = traceback.format_exc()
                self._logger.error(f"Run {run_id} attempt {attempt + 1} failed: {e}")

                if attempt < retry_config["max_retries"]:
                    # Schedule retry
                    backoff = min(
                        retry_config["backoff_seconds"] * (retry_config["backoff_multiplier"] ** attempt),
                        retry_config["max_backoff_seconds"],
                    )
                    next_retry_at = datetime.now(timezone.utc).timestamp() + backoff
                    self._history.record_retry(
                        run_id,
                        attempt + 1,
                        datetime.fromtimestamp(next_retry_at, tz=timezone.utc).isoformat(),
                    )
                    self._logger.info(f"Retrying run {run_id} in {backoff}s (attempt {attempt + 2})")
                    time.sleep(backoff)
                else:
                    # Max retries exhausted
                    self._finish_run(
                        run_id,
                        "failed",
                        error=last_error,
                        traceback_str=last_traceback,
                    )
                    return

    def _run_pipeline(self, run_id: str, profile: str) -> dict:
        """Run the actual DailyRun pipeline."""
        # Add project root to path
        project_root = str(Path(__file__).parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        from core.config_loader import load_config
        from workflows.daily_run import DailyRun

        # Resolve config path
        if profile == "client_acq":
            config_path = "config.client_acq.yaml"
        elif profile == "algeria_ecom":
            config_path = "config.algeria_ecom.yaml"
        else:
            config_path = os.environ.get("MARKET_INTEL_CONFIG", "config.yaml")

        # Update progress
        with self._run_lock:
            if run_id in self._active_runs:
                self._active_runs[run_id]["progress"] = "loading_config"

        cfg = load_config(config_path)

        with self._run_lock:
            if run_id in self._active_runs:
                self._active_runs[run_id]["progress"] = "running_pipeline"

        workflow = DailyRun(cfg)
        summary = workflow.run()

        return summary

    def _finish_run(
        self,
        run_id: str,
        status: str,
        summary: dict | None = None,
        error: str | None = None,
        traceback_str: str | None = None,
    ) -> None:
        """Finish a run — update history + active runs."""
        completed_at = datetime.now(timezone.utc).isoformat()

        self._history.record_completion(
            run_id, status, summary=summary, error=error, traceback_str=traceback_str
        )

        with self._run_lock:
            if run_id in self._active_runs:
                self._active_runs[run_id]["status"] = status
                self._active_runs[run_id]["completed_at"] = completed_at
                if summary:
                    self._active_runs[run_id]["summary"] = summary
                if error:
                    self._active_runs[run_id]["error"] = error
                # Remove from active runs (keep in history)
                del self._active_runs[run_id]

            self._cancel_flags.discard(run_id)

        self._logger.info(f"Run {run_id} finished: {status}")


# Singleton accessor
def get_scheduler() -> MarketIntelScheduler:
    """Get the scheduler singleton."""
    return MarketIntelScheduler()
