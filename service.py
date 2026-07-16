"""
Service entry point — run Market-Intel as a continuous daemon.

The service runs:
  1. FastAPI app (uvicorn) — REST API + dashboard, always available
  2. APScheduler (in-process) — scheduled pipeline runs

Usage:
  python service.py                     # default (0.0.0.0:8000)
  python service.py --port 9000        # custom port
  python service.py --workers 4        # multiple uvicorn workers
  python service.py --reload           # development mode

Or via uvicorn directly:
  uvicorn api.app:app --host 0.0.0.0 --port 8000

The scheduler starts automatically on app startup (via lifespan hook).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Ensure project root on path
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main():
    parser = argparse.ArgumentParser(description="Market-Intel Service")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    parser.add_argument("--workers", type=int, default=1, help="Number of uvicorn workers")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (development)")
    parser.add_argument("--log-level", default="info", help="Log level")
    args = parser.parse_args()

    import uvicorn

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                    Market-Intel Service                       ║
╠══════════════════════════════════════════════════════════════╣
║  API:     http://{args.host}:{args.port}/api/v1               ║
║  Docs:    http://{args.host}:{args.port}/docs                 ║
║  Dashboard: http://{args.host}:{args.port}/dashboard          ║
║  Scheduler: auto-starts on app startup                        ║
╚══════════════════════════════════════════════════════════════╝
""")

    uvicorn.run(
        "api.app:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
