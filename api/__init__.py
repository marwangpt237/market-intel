"""
FastAPI Application — Phase 1 of productization.

Exposes the Market-Intel engine through REST APIs while preserving:
  - All existing architecture (collectors, processors, country/vertical packs)
  - All deterministic decision making
  - All current tests passing
  - Backward compatibility with GitHub Actions / main.py CLI

Structure:
  api/
    __init__.py
    app.py              — FastAPI app instance + lifespan
    config.py           — API-specific configuration
    dependencies.py     — shared dependencies (DB, scheduler)
    routers/
      health.py         — health checks
      runs.py           — manual run triggers, run history
      reports.py        — list/get reports
      collectors.py     — collector registry + health
      claims.py         — claims + evidence (validation engine)
      decisions.py      — decision ledger
      search.py         — search across items
      stats.py          — dashboard metrics / moat metrics

The app can be run via:
    uvicorn api.app:app --reload  (development)
    uvicorn api.app:app --host 0.0.0.0 --port 8000  (production)

Or programmatically:
    from api.app import app
    # use with uvicorn programmatically
"""
