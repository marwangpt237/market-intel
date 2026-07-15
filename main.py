"""
Market-Intel — Entry point.

Runs the daily intelligence collection pipeline.
Can be invoked directly or via GitHub Actions.
"""
from __future__ import annotations

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config_loader import load_config
from core.logger import setup_logging
from workflows.daily_run import DailyRun


def main():
    # Setup logging
    config = load_config(os.environ.get("MARKET_INTEL_CONFIG", "config.yaml"))
    log_level = config.general.get("environment") == "development" and "DEBUG" or "INFO"
    logger = setup_logging(log_level)

    logger.info("Market-Intel starting up")

    # Run the pipeline
    workflow = DailyRun(config)
    summary = workflow.run()

    # Print summary for GitHub Actions logs
    print("\n" + "=" * 60)
    print("Market-Intel Run Summary")
    print("=" * 60)
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print("=" * 60)

    # Exit with error if no data collected
    if summary["status"] == "no_data":
        logger.warning("No data collected — check collector configurations")
        sys.exit(1)

    logger.info("Market-Intel shutdown complete")


if __name__ == "__main__":
    main()
