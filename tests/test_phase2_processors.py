"""Unit tests for Phase 2 processors."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.models import RawItem, ProcessedItem
from processors.similarity_dedup import SimilarityDedupProcessor, jaccard_similarity, tokenize
from processors.entity_extraction import EntityExtractionProcessor
from processors.competitor_detection import CompetitorDetectionProcessor
from processors.pain_point_extraction import PainPointExtractionProcessor
from processors.buying_signal import BuyingSignalProcessor
from processors.topic_clustering import TopicClusteringProcessor, build_tfidf_vectors, cosine_similarity


def make_item(title: str, url: str, body: str = "", **kwargs) -> ProcessedItem:
    raw = RawItem.create(source="test", source_name="Test", title=title, url=url, body=body, **kwargs)
    return ProcessedItem.from_raw(raw)


# ─── Similarity Dedup ────────────────────────────────────────────────────

def test_jaccard_similarity():
    assert jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0
    assert 0 < jaccard_similarity({"a", "b", "c"}, {"a", "b", "d"}) < 1.0


def test_similarity_dedup_near_duplicates():
    items = [
        make_item("Maltego pricing is too expensive", "https://reddit.com/1"),
        make_item("Maltego pricing is too expensive!", "https://reddit.com/2"),
        make_item("Google announces new update", "https://reddit.com/3"),
    ]
    processor = SimilarityDedupProcessor({"title_threshold": 0.5})
    result = processor.process(items)
    assert len(result) == 2  # near-duplicate removed


def test_similarity_dedup_url_match():
    items = [
        make_item("Title A", "https://example.com/article?utm=1"),
        make_item("Title B", "https://example.com/article?utm=2"),
    ]
    processor = SimilarityDedupProcessor({"url_normalize": True})
    result = processor.process(items)
    assert len(result) == 1  # same base URL


# ─── Entity Extraction ───────────────────────────────────────────────────

def test_entity_extraction_companies():
    item = make_item("Google and Microsoft announce partnership", "https://example.com/1", body="Apple also involved")
    processor = EntityExtractionProcessor()
    result = processor.process([item])
    companies = result[0].metadata["entities"]["companies"]
    assert "google" in companies
    assert "microsoft" in companies
    assert "apple" in companies


def test_entity_extraction_products():
    item = make_item("Comparing ChatGPT vs Claude for marketing", "https://example.com/1")
    processor = EntityExtractionProcessor()
    result = processor.process([item])
    products = result[0].metadata["entities"]["products"]
    assert "chatgpt" in products
    assert "claude" in products


def test_entity_extraction_handles():
    item = make_item("Check out @johndoe on Twitter", "https://example.com/1")
    processor = EntityExtractionProcessor()
    result = processor.process([item])
    people = result[0].metadata["entities"]["people"]
    assert "@johndoe" in people


# ─── Competitor Detection ────────────────────────────────────────────────

def test_competitor_direct_mention():
    item = make_item("Maltego is too expensive", "https://reddit.com/1", body="Looking for alternatives")
    processor = CompetitorDetectionProcessor()
    result = processor.process([item])
    mentions = result[0].metadata.get("competitor_mentions", [])
    assert len(mentions) > 0
    assert mentions[0]["competitor"] == "maltego"
    assert mentions[0]["signal"] == "seeking_alternative"


def test_competitor_pricing_complaint():
    item = make_item("HubSpot pricing is insane", "https://reddit.com/1")
    processor = CompetitorDetectionProcessor()
    result = processor.process([item])
    mentions = result[0].metadata.get("competitor_mentions", [])
    assert len(mentions) > 0
    assert mentions[0]["signal"] == "pricing_complaint"


def test_competitor_no_mention():
    item = make_item("Beautiful sunset today", "https://reddit.com/1")
    processor = CompetitorDetectionProcessor()
    result = processor.process([item])
    assert "competitor_mentions" not in result[0].metadata or len(result[0].metadata["competitor_mentions"]) == 0


# ─── Pain-Point Extraction ───────────────────────────────────────────────

def test_pain_point_pricing():
    item = make_item("This tool is too expensive", "https://reddit.com/1")
    processor = PainPointExtractionProcessor()
    result = processor.process([item])
    pain_points = result[0].metadata.get("pain_points", [])
    assert len(pain_points) > 0
    assert any(pp["category"] == "pricing" for pp in pain_points)


def test_pain_point_bug():
    item = make_item("The app keeps crashing", "https://reddit.com/1", body="It's broken and frustrating")
    processor = PainPointExtractionProcessor()
    result = processor.process([item])
    pain_points = result[0].metadata.get("pain_points", [])
    assert any(pp["category"] == "bug" for pp in pain_points)


def test_pain_point_feature_request():
    item = make_item("Wish it had dark mode", "https://reddit.com/1")
    processor = PainPointExtractionProcessor()
    result = processor.process([item])
    pain_points = result[0].metadata.get("pain_points", [])
    assert any(pp["type"] == "feature_request" for pp in pain_points)


# ─── Buying Signals ──────────────────────────────────────────────────────

def test_buying_signal_evaluation():
    item = make_item("Comparing SEMrush vs Ahrefs", "https://reddit.com/1", body="Testing both right now")
    processor = BuyingSignalProcessor()
    result = processor.process([item])
    signals = result[0].metadata.get("buying_signals", [])
    assert len(signals) > 0
    assert any(s["type"] == "evaluation" for s in signals)


def test_buying_signal_budget():
    item = make_item("Looking for a tool under $50/month", "https://reddit.com/1")
    processor = BuyingSignalProcessor()
    result = processor.process([item])
    signals = result[0].metadata.get("buying_signals", [])
    assert any(s["type"] == "budget" for s in signals)


def test_buying_signal_decision():
    item = make_item("Ready to buy a subscription this week", "https://reddit.com/1")
    processor = BuyingSignalProcessor()
    result = processor.process([item])
    signals = result[0].metadata.get("buying_signals", [])
    assert any(s["type"] == "decision" or s["type"] == "urgency" for s in signals)


def test_buying_intent_score():
    item = make_item("Comparing tools, budget $100/month, need urgently", "https://reddit.com/1", body="Ready to buy")
    processor = BuyingSignalProcessor()
    result = processor.process([item])
    assert result[0].metadata["buying_intent"] > 0.5


# ─── Topic Clustering ────────────────────────────────────────────────────

def test_tfidf_vectors():
    items = [
        make_item("SEO tools comparison", "https://1.com"),
        make_item("SEO ranking factors", "https://2.com"),
        make_item("Cooking recipes", "https://3.com"),
    ]
    vectors = build_tfidf_vectors(items)
    assert len(vectors) == 3
    # SEO items should be more similar to each other than to cooking
    sim_seo = cosine_similarity(vectors[0], vectors[1])
    sim_other = cosine_similarity(vectors[0], vectors[2])
    assert sim_seo > sim_other


def test_topic_clustering_groups_similar():
    items = [
        make_item("SEO tools for marketing", "https://1.com", body="SEO ranking backlinks"),
        make_item("Best SEO software 2026", "https://2.com", body="SEO tools ranking"),
        make_item("Cooking pasta recipes", "https://3.com", body="pasta italian food"),
        make_item("Italian food guide", "https://4.com", body="pasta cooking recipes"),
    ]
    processor = TopicClusteringProcessor({"similarity_threshold": 0.15, "min_cluster_size": 2})
    result = processor.process(items)
    # SEO items should be in the same cluster
    seo_cluster = result[0].metadata.get("cluster_id")
    assert seo_cluster is not None
    assert seo_cluster == result[1].metadata.get("cluster_id")
    # Different from cooking cluster
    assert result[0].metadata.get("cluster_id") != result[2].metadata.get("cluster_id")
