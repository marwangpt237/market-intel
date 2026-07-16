"""
Scheduler — APScheduler-based job management for Market-Intel.

Phase 2 of productization. Replaces GitHub Actions as the primary
execution engine.

Features:
  - Job management (add, remove, list, pause, resume)
  - Manual runs (trigger immediately)
  - Scheduled runs (cron-like schedules per profile)
  - Collector-specific schedules (run only specific collectors)
  - Retry policies (exponential backoff on failure)
  - Run history (persisted to SQLite)
  - Run status (queued, running, completed, failed, cancelled)
  - Cancellation (best-effort — marks as cancelling)
  - Metrics (success rate, avg duration, items collected)

The scheduler runs in-process with the FastAPI app via uvicorn.
"""
