"""Tests for Phase 11 — Raw Data Archiver + Moat Metrics + new collectors."""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.models import RawItem, ProcessedItem
from storage.raw_archiver import RawDataArchiver
from collectors.marketplace.algeria_news_collector import AlgerianNewsCollector
from collectors.marketplace.jumia_dz_collector import JumiaDZCollector
from collectors.marketplace.algeria_realestate_collector import AlgerianRealEstateCollector
from collectors.marketplace.algeria_tenders_collector import AlgerianTendersCollector


# ─── Raw Data Archiver ─────────────────────────────────────────────────

def test_archiver_archives_items():
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "archive.db")
        archiver = RawDataArchiver(db_path)

        items = [
            RawItem.create(source="test", source_name="Test", title="Item 1", url="http://1.com"),
            RawItem.create(source="test", source_name="Test", title="Item 2", url="http://2.com"),
        ]
        count = archiver.archive_items(items)
        assert count == 2

        stats = archiver.get_stats()
        assert stats["total_items_archived"] == 2
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_archiver_is_idempotent():
    """Same items archived twice → only counted once."""
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "archive.db")
        archiver = RawDataArchiver(db_path)

        items = [RawItem.create(source="test", source_name="Test", title="Item 1", url="http://1.com")]
        archiver.archive_items(items)
        count = archiver.archive_items(items)  # same items again
        assert count == 0  # already archived

        stats = archiver.get_stats()
        assert stats["total_items_archived"] == 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_archiver_tracks_sources():
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "archive.db")
        archiver = RawDataArchiver(db_path)

        items = [
            RawItem.create(source="rss", source_name="APS", title="1", url="http://1.com"),
            RawItem.create(source="rss", source_name="El Watan", title="2", url="http://2.com"),
            RawItem.create(source="reddit", source_name="r/algeria", title="3", url="http://3.com"),
        ]
        archiver.archive_items(items)

        stats = archiver.get_stats()
        assert stats["total_distinct_sources"] == 2  # rss + reddit
        assert stats["total_distinct_source_names"] == 3
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_archiver_get_items_count_by_source():
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "archive.db")
        archiver = RawDataArchiver(db_path)

        items = [
            RawItem.create(source="rss", source_name="A", title="1", url="http://1.com"),
            RawItem.create(source="rss", source_name="B", title="2", url="http://2.com"),
            RawItem.create(source="reddit", source_name="C", title="3", url="http://3.com"),
        ]
        archiver.archive_items(items)

        assert archiver.get_items_count_by_source("rss") == 2
        assert archiver.get_items_count_by_source("reddit") == 1
        assert archiver.get_items_count_by_source("unknown") == 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_archiver_handles_empty_list():
    tmpdir = tempfile.mkdtemp()
    try:
        archiver = RawDataArchiver(os.path.join(tmpdir, "archive.db"))
        count = archiver.archive_items([])
        assert count == 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ─── New Collectors ────────────────────────────────────────────────────

def test_algeria_news_collector_metadata():
    c = AlgerianNewsCollector()
    assert c.metadata.name == "algeria_news"
    assert c.metadata.country == "DZ"
    assert c.metadata.category == "news"
    assert c.metadata.reliability == 0.80


def test_algeria_news_has_default_sources():
    c = AlgerianNewsCollector()
    assert len(c._sources) >= 5
    source_names = [s["name"] for s in c._sources]
    assert "El Khabar" in source_names
    assert "El Watan" in source_names


def test_jumia_dz_collector_metadata():
    c = JumiaDZCollector()
    assert c.metadata.name == "jumia_dz"
    assert c.metadata.country == "DZ"
    assert c.metadata.category == "marketplace"
    assert "product" in c.metadata.entity_types
    assert c.metadata.reliability == 0.80


def test_jumia_dz_has_categories():
    c = JumiaDZCollector()
    assert len(c.CATEGORIES) >= 4
    assert "smartphones" in c.CATEGORIES


def test_algeria_realestate_collector_metadata():
    c = AlgerianRealEstateCollector()
    assert c.metadata.name == "algeria_realestate"
    assert c.metadata.country == "DZ"
    assert c.metadata.category == "real_estate"
    assert "property" in c.metadata.entity_types


def test_algeria_tenders_collector_metadata():
    c = AlgerianTendersCollector()
    assert c.metadata.name == "algeria_tenders"
    assert c.metadata.country == "DZ"
    assert c.metadata.category == "government"
    assert c.metadata.reliability == 0.90  # official


def test_all_new_collectors_return_list():
    """collect() should always return a list, even on network failure."""
    for CollectorClass in [AlgerianNewsCollector, JumiaDZCollector, AlgerianRealEstateCollector, AlgerianTendersCollector]:
        c = CollectorClass({"max_items_per_source": 1, "max_items": 1})
        items = c.collect()
        assert isinstance(items, list)
