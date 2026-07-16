"""
Market-Intel — Entry point.

Runs the daily intelligence collection pipeline.
Can be invoked directly or via GitHub Actions.

Profiles:
  default     — marketing intelligence (default config.yaml)
  client_acq  — client acquisition mode (config.client_acq.yaml)

Activate via:
  python main.py
  python main.py --profile client_acq
  MARKET_INTEL_PROFILE=client_acq python main.py
"""
from __future__ import annotations

import sys
import os
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config_loader import load_config
from core.logger import setup_logging
from workflows.daily_run import DailyRun


def resolve_config_path(profile: str | None = None) -> str:
    """Resolve which config file to load based on profile."""
    # Priority: --profile flag > MARKET_INTEL_CONFIG env > MARKET_INTEL_PROFILE env > default
    if profile is None:
        profile = os.environ.get("MARKET_INTEL_PROFILE")

    if profile == "client_acq":
        return "config.client_acq.yaml"
    elif profile == "algeria_ecom":
        return "config.algeria_ecom.yaml"
    elif profile and profile != "default":
        # Allow custom profiles: config.<name>.yaml
        candidate = f"config.{profile}.yaml"
        if os.path.exists(candidate):
            return candidate

    # Fallback to MARKET_INTEL_CONFIG env or default
    return os.environ.get("MARKET_INTEL_CONFIG", "config.yaml")


def main():
    parser = argparse.ArgumentParser(description="Market-Intel intelligence platform")
    parser.add_argument(
        "--profile", "-p",
        choices=["default", "client_acq", "algeria_ecom"],
        default=None,
        help="Configuration profile to use (default: marketing intelligence)",
    )
    args = parser.parse_args()

    config_path = resolve_config_path(args.profile)

    # Setup logging
    config = load_config(config_path)
    log_level = config.general.get("environment") == "development" and "DEBUG" or "INFO"
    logger = setup_logging(log_level)

    profile_name = args.profile or os.environ.get("MARKET_INTEL_PROFILE", "default")
    logger.info(f"Market-Intel starting up — profile: {profile_name}, config: {config_path}")

    # Run the pipeline
    workflow = DailyRun(config)
    summary = workflow.run()

    # Print summary for GitHub Actions logs
    print("\n" + "=" * 60)
    print(f"Market-Intel Run Summary — profile: {profile_name}")
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
