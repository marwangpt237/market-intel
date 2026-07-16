"""API configuration — reads from main config.yaml + env vars."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class APIConfig:
    """API-specific configuration."""

    # Paths
    PROJECT_ROOT: Path = Path(__file__).parent.parent
    CONFIG_PATH: str = os.environ.get("MARKET_INTEL_CONFIG", str(PROJECT_ROOT / "config.yaml"))
    REPORTS_DIR: Path = PROJECT_ROOT / "reports"
    DATA_DIR: Path = PROJECT_ROOT / "data"
    ACTIONS_DIR: Path = PROJECT_ROOT / "actions"

    # API settings
    API_TITLE: str = "Market-Intel API"
    API_DESCRIPTION: str = "Algeria-first Market Intelligence Platform — production API"
    API_VERSION: str = "1.0.0"
    API_PREFIX: str = "/api/v1"

    # Database (read from main config)
    DB_PATH: str = os.environ.get(
        "MARKET_INTEL_DB",
        str(PROJECT_ROOT / "data" / "market_intel.db"),
    )
    ARCHIVE_DB_PATH: str = os.environ.get(
        "MARKET_INTEL_ARCHIVE_DB",
        str(PROJECT_ROOT / "data" / "market_intel_archive.db"),
    )

    # CORS (for dashboard)
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
    ]

    # Run settings
    MAX_CONCURRENT_RUNS: int = 1  # only one pipeline run at a time


# Singleton
config = APIConfig()
