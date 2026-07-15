"""Unit tests for SQLite storage + entity graph + scoring."""
import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.models import RawItem, ProcessedItem
from storage.sqlite_store import SQLiteStorage
from processors.entity_graph import EntityGraphProcessor
from processors.scoring import ScoringProcessor


def make_item(title: str, url: str, body: str = "", **kwargs) -> ProcessedItem:
    raw = RawItem.create(source="test", source_name="Test", title=title, url=url, body=body, **kwargs)
    return ProcessedItem.from_raw(raw)


# ─── SQLite Storage ──────────────────────────────────────────────────────

def test_sqlite_save_and_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        storage = SQLiteStorage({"path": db_path, "retention_days": 365})
        items = [
            {"id": "1", "title": "Test 1", "source": "test", "source_name": "Test",
             "url": "http://1.com", "collected_at": "2026-01-01T00:00:00+00:00",
             "keywords": ["marketing", "seo"], "tags": ["tech"], "metadata": {},
             "sentiment": "neutral", "buying_intent": 0.5},
        ]
        storage.save(items, "run_1")
        loaded = storage.load_recent(days=365)
        assert len(loaded) >= 1
        assert loaded[0]["title"] == "Test 1"
        assert "marketing" in loaded[0]["keywords"]


def test_sqlite_keyword_history():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        storage = SQLiteStorage({"path": db_path})
        storage.save([
            {"id": "1", "title": "T1", "source": "t", "source_name": "T", "url": "http://1.com",
             "collected_at": "2026-07-15T00:00:00+00:00", "keywords": ["seo", "marketing"]},
            {"id": "2", "title": "T2", "source": "t", "source_name": "T", "url": "http://2.com",
             "collected_at": "2026-07-15T00:00:00+00:00", "keywords": ["seo", "email"]},
        ], "run_1")
        history = storage.load_keyword_history(days=365)
        assert history.get("seo") == 2
        assert history.get("marketing") == 1


# ─── Entity Graph ────────────────────────────────────────────────────────

def test_entity_graph_builds_nodes():
    items = [
        make_item("HubSpot is expensive", "http://1.com", body="Looking for alternatives"),
        make_item("SEMrush review", "http://2.com", body="Great SEO tool"),
    ]
    # Add entities + pain points manually
    items[0].metadata["entities"] = {"companies": ["hubspot"], "products": [], "people": []}
    items[0].metadata["pain_points"] = [{"category": "pricing", "severity": "high", "text": "expensive"}]
    items[1].metadata["entities"] = {"companies": ["semrush"], "products": [], "people": []}

    processor = EntityGraphProcessor()
    result = processor.process(items)

    graph = result[0].metadata.get("_entity_graph", {})
    assert graph["stats"]["total_nodes"] > 0
    assert graph["stats"]["companies"] >= 2  # hubspot + semrush
    assert graph["stats"]["pain_points"] >= 1  # pricing


# ─── Scoring Engine ──────────────────────────────────────────────────────

def test_scoring_calculates_opportunity():
    items = [
        make_item("Maltego pricing is insane", "http://1.com", body="Need cheaper alternative"),
    ]
    items[0].metadata["entities"] = {"companies": ["maltego"], "products": [], "people": []}
    items[0].metadata["pain_points"] = [{"category": "pricing", "severity": "high", "text": "insane"}]
    items[0].metadata["buying_signals"] = [{"type": "budget", "confidence": 0.8, "text": "cheaper"}]
    items[0].metadata["competitor_mentions"] = [{"competitor": "maltego", "signal": "pricing_complaint", "category": "OSINT"}]

    processor = ScoringProcessor()
    result = processor.process(items)

    scores = result[0].metadata.get("_scores", {})
    company_scores = scores.get("company_scores", [])
    assert len(company_scores) > 0

    maltego = next((s for s in company_scores if s["entity"] == "maltego"), None)
    assert maltego is not None
    assert maltego["opportunity_score"] > 0
    assert maltego["competitor_weakness_score"] > 0


def test_scoring_generates_insights():
    items = [
        make_item("HubSpot too expensive, looking for alternative", "http://1.com"),
    ]
    items[0].metadata["entities"] = {"companies": ["hubspot"], "products": [], "people": []}
    items[0].metadata["pain_points"] = [{"category": "pricing", "severity": "high", "text": "expensive"}]
    items[0].metadata["buying_signals"] = [{"type": "evaluation", "confidence": 0.7, "text": "alternative"}]
    items[0].metadata["competitor_mentions"] = [{"competitor": "hubspot", "signal": "seeking_alternative", "category": "Marketing"}]

    processor = ScoringProcessor()
    result = processor.process(items)

    scores = result[0].metadata.get("_scores", {})
    insights = scores.get("insights", [])
    assert len(insights) > 0
    assert any("hubspot" in i.lower() for i in insights)
