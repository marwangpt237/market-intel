"""Scheduler configuration — default jobs + retry policies."""
from __future__ import annotations


# Default scheduled jobs (profiles + intervals)
DEFAULT_JOBS: list[dict] = [
    {
        "id": "default_marketing",
        "name": "Marketing Intelligence (default profile)",
        "profile": "default",
        "cron": "0 */6 * * *",  # every 6 hours
        "enabled": True,
        "max_retries": 2,
        "retry_backoff_seconds": 60,
    },
    {
        "id": "algeria_ecom",
        "name": "Algeria E-commerce Intelligence",
        "profile": "algeria_ecom",
        "cron": "30 */12 * * *",  # every 12 hours at :30
        "enabled": True,
        "max_retries": 2,
        "retry_backoff_seconds": 60,
    },
    {
        "id": "client_acq",
        "name": "Client Acquisition (prospects scan)",
        "profile": "client_acq",
        "cron": "15 */12 * * *",  # every 12 hours at :15
        "enabled": False,  # opt-in
        "max_retries": 1,
        "retry_backoff_seconds": 120,
    },
]


# Retry policy defaults
DEFAULT_RETRY_POLICY = {
    "max_retries": 2,
    "backoff_seconds": 60,
    "backoff_multiplier": 2.0,
    "max_backoff_seconds": 600,
    "retryable_errors": [
        "ConnectionError",
        "TimeoutError",
        "HTTPError 5xx",
        "HTTPError 429",
    ],
}


# Run status values
RUN_STATUS_QUEUED = "queued"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_CANCELLED = "cancelled"
RUN_STATUS_CANCELLING = "cancelling"
RUN_STATUS_RETRYING = "retrying"
