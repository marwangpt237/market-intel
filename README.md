# Market-Intel

Autonomous marketing intelligence platform that closes the loop:
**Collect → Analyze → Score → Decide → Act → Measure → Learn**.

It doesn't just report opportunities — it selects, executes, evaluates, and continuously improves actions.

## Architecture

```
market-intel/
├── collectors/          # Data sources
│   ├── base.py
│   ├── reddit_collector.py
│   ├── rss_collector.py
│   ├── google_news_collector.py
│   ├── hackernews_collector.py       # Phase 3 — Algolia API
│   ├── github_issues_collector.py    # Phase 3 — REST API
│   ├── producthunt_collector.py      # Phase 3
│   ├── g2_collector.py               # Phase 3
│   └── jobboard_collector.py         # Phase 3 — remoteok / workinstartups RSS
├── processors/          # Transform + analyze + score + decide
│   ├── base.py
│   ├── similarity_dedup.py           # Phase 2 — TF-IDF cosine similarity
│   ├── enrich.py                     # Phase 1 — sentiment + keywords + read time
│   ├── entity_extraction.py          # Phase 2 — companies / products / people
│   ├── competitor_detection.py       # Phase 2
│   ├── pain_point_extraction.py      # Phase 2
│   ├── buying_signal.py              # Phase 2 — budget / evaluation / timing
│   ├── topic_clustering.py           # Phase 2 — TF-IDF + Jaccard
│   ├── trend_detection.py            # Phase 2 — spike / hot / rising / declining
│   ├── entity_graph.py               # Phase 3 — companies ↔ products ↔ topics ↔ pain points
│   ├── scoring.py                    # Phase 3 — opportunity / threat / trend / weakness scores
│   ├── decision_engine.py            # Phase 4 — ranked action recommendations
│   ├── execution_engine.py           # Phase 4 — generates GitHub issues, emails, ad copy, blog briefs
│   ├── analytics_engine.py           # Phase 4 — tracks actions + outcomes in SQLite
│   └── learning_engine.py            # Phase 4 — adjusts scoring weights from outcomes
├── storage/             # Persist data
│   ├── base.py
│   ├── json_store.py                 # Phase 1 — versioned JSON snapshots
│   └── sqlite_store.py               # Phase 3 — historical queries + entity-graph joins
├── reports/             # Generate output
│   ├── base.py
│   ├── markdown_report.py            # Phase 1 — daily markdown digest
│   ├── intelligence_report.py        # Phase 2 — actionable insights summary
│   └── decision_report.py            # Phase 4 — decisions + actions + learning adjustments
├── workflows/
│   └── daily_run.py                  # Orchestrates the full closed loop
├── core/                # Shared infrastructure
├── config/
│   └── loader.py
├── tests/               # 44 unit tests covering all phases
├── data/                # SQLite DB + learning weights + metrics template
├── actions/             # Phase 4 — generated markdown artifacts per decision
└── config.yaml          # Main configuration
```

## The Closed Loop

```
   ┌──────────────────────────────────────────────────────────┐
   │                                                          ▼
Collect     →  Analyze    →  Score    →  Decide   →  Act    →  Measure  →  Learn
                                                                 │
                                                                 ▼
                                                       Adjusts scoring weights
                                                       for next run
```

- **Collect**: 8 sources — Reddit, RSS, Google News, Hacker News, GitHub Issues, Product Hunt, G2, Job boards
- **Analyze**: Entity extraction, competitor detection, pain-point extraction, buying-signal detection, topic clustering, trend detection, entity graph
- **Score**: Opportunity / Threat / Trend / Competitor-weakness scores (0–100)
- **Decide**: Rule-based decision engine → ranked P0/P1/P2/P3 actions with rationale + evidence
- **Act**: Execution engine generates ready-to-publish markdown artifacts (GitHub issues, email sequences, campaign briefs, blog outlines, watchlist entries)
- **Measure**: Analytics engine records every action in SQLite; outcomes tracked via `metrics_input_template.json`
- **Learn**: Learning engine computes per-bucket outcomes vs baseline → adjusts threshold weights → persists to `data/learning_weights.json` → next run uses new weights

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Run
python main.py

# Test
pytest tests/ -v
```

## Configuration

Edit `config.yaml` to control:
- Which collectors are enabled
- Which subreddits / RSS feeds / Google News queries to track
- Processor settings (dedup keys, enrichment options)
- Storage path and retention
- Report format and sections

## Adding a New Collector

1. Create `collectors/my_collector.py`
2. Inherit from `BaseCollector`
3. Implement `_fetch()` → return `list[RawItem]`
4. Register in `workflows/daily_run.py`

```python
from collectors.base import BaseCollector
from core.models import RawItem

class MyCollector(BaseCollector):
    name = "my_source"

    def _fetch(self) -> list[RawItem]:
        # Your logic here
        return [RawItem.create(
            source="my_source",
            source_name="My Source",
            title="...",
            url="...",
        )]
```

## Automation

GitHub Actions runs the pipeline every 6 hours. Data and reports are committed back to the repo automatically.

## Design Principles

- **Modular**: Every collector, processor, storage, and report is replaceable.
- **DI**: Components receive dependencies via constructor, never import each other directly.
- **Config-driven**: Everything controlled via `config.yaml`.
- **Stdlib-first**: Only dependency is `pyyaml`. HTTP, XML parsing, JSON storage all use stdlib.
- **Observable**: Structured JSON logging to stdout.
- **Resilient**: Retry with exponential backoff on all network calls.

## License

MIT
