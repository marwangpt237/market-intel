"""Unit tests for Market-Intel core models."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.models import RawItem, ProcessedItem, generate_id


def test_raw_item_create():
    item = RawItem.create(
        source="reddit",
        source_name="r/test",
        title="Test Post",
        url="https://example.com/post1",
    )
    assert item.id is not None
    assert len(item.id) == 16
    assert item.source == "reddit"
    assert item.title == "Test Post"
    assert item.collected_at  # auto-generated


def test_generate_id_deterministic():
    id1 = generate_id("reddit", "https://example.com/post1")
    id2 = generate_id("reddit", "https://example.com/post1")
    assert id1 == id2


def test_generate_id_different():
    id1 = generate_id("reddit", "https://example.com/post1")
    id2 = generate_id("rss", "https://example.com/post1")
    assert id1 != id2


def test_processed_item_from_raw():
    raw = RawItem.create(
        source="rss",
        source_name="Test Feed",
        title="Hello World",
        url="https://example.com/feed1",
        body="This is the body text",
        score=42,
    )
    processed = ProcessedItem.from_raw(raw)
    assert processed.id == raw.id
    assert processed.title == raw.title
    assert processed.score == 42
    assert processed.dedup_key  # auto-generated


def test_raw_item_to_dict():
    item = RawItem.create(
        source="test",
        source_name="Test",
        title="Dict Test",
        url="https://example.com/dict",
    )
    d = item.to_dict()
    assert d["source"] == "test"
    assert d["title"] == "Dict Test"
    assert "collected_at" in d
