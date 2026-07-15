"""Unit tests for processors."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.models import RawItem, ProcessedItem
from processors.dedup import DedupProcessor
from processors.enrich import EnrichProcessor


def make_item(title: str, url: str, **kwargs) -> ProcessedItem:
    raw = RawItem.create(source="test", source_name="Test", title=title, url=url, **kwargs)
    return ProcessedItem.from_raw(raw)


def test_dedup_removes_duplicates():
    items = [
        make_item("Same Title", "https://example.com/1"),
        make_item("Same Title", "https://example.com/2"),  # dup by title
        make_item("Different", "https://example.com/3"),
    ]
    processor = DedupProcessor({"keys": ["title"]})
    result = processor.process(items)
    assert len(result) == 2


def test_dedup_by_url():
    items = [
        make_item("Title A", "https://example.com/same"),
        make_item("Title B", "https://example.com/same"),  # dup by URL
        make_item("Title C", "https://example.com/different"),
    ]
    processor = DedupProcessor({"keys": ["url"]})
    result = processor.process(items)
    assert len(result) == 2


def test_enrich_adds_keywords():
    item = make_item("Marketing Growth Strategy", "https://example.com/1")
    processor = EnrichProcessor({"add_keywords": True})
    result = processor.process([item])
    assert len(result[0].keywords) > 0
    assert "marketing" in result[0].keywords or "growth" in result[0].keywords


def test_enrich_detects_sentiment():
    item_pos = make_item("Revenue Growth and Success", "https://example.com/pos")
    item_neg = make_item("Revenue Decline and Loss", "https://example.com/neg")
    processor = EnrichProcessor({"add_sentiment": True})
    result = processor.process([item_pos, item_neg])
    assert result[0].sentiment == "positive"
    assert result[1].sentiment == "negative"


def test_enrich_read_time():
    item = make_item("Test", "https://example.com/1", body="A" * 500)
    processor = EnrichProcessor({"add_read_time": True})
    result = processor.process([item])
    assert result[0].read_time_minutes >= 1
