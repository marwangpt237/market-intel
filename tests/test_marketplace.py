"""Unit tests for Phase 10 — Collector Marketplace."""
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.models import RawItem
from collectors.marketplace.base import (
    MarketplaceCollector, CollectorMetadata, CollectorRegistry, CollectorHealth,
)
from collectors.marketplace.health import CollectorHealthMonitor
from collectors.marketplace.rss_collector import MarketplaceRSSCollector
from collectors.marketplace.ouedkniss_collector import OuedknissCollector
from collectors.marketplace.algeria_jobs_collector import AlgerianJobBoardCollector
from collectors.marketplace.algeria_forum_collector import AlgerianForumCollector
from collectors.marketplace.algeria_gov_collector import AlgerianGovCollector


# ─── Collector Metadata ────────────────────────────────────────────────

def test_collector_metadata_to_dict():
    meta = CollectorMetadata(
        name="test_source",
        country="DZ",
        category="news",
        entity_types=["article"],
        description="Test source",
        reliability=0.85,
    )
    d = meta.to_dict()
    assert d["name"] == "test_source"
    assert d["country"] == "DZ"
    assert d["reliability"] == 0.85


def test_collector_metadata_defaults():
    meta = CollectorMetadata(name="x", country="US", category="news", entity_types=["article"])
    assert meta.rate_limit_per_hour == 60
    assert meta.reliability == 0.70
    assert meta.cost_per_call == 0.0
    assert meta.required_credentials == []
    assert meta.health_status == "unknown"


# ─── Collector Registry ────────────────────────────────────────────────

def test_registry_register_and_get():
    # Create a test collector
    class TestCollector(MarketplaceCollector):
        metadata = CollectorMetadata(
            name="test_unique_1",
            country="DZ",
            category="test",
            entity_types=["test_entity"],
        )
        def collect(self):
            return []

    collector = TestCollector()
    CollectorRegistry.register(collector)

    retrieved = CollectorRegistry.get("test_unique_1")
    assert retrieved is not None
    assert retrieved.metadata.name == "test_unique_1"


def test_registry_list_by_country():
    class TestDZCollector(MarketplaceCollector):
        metadata = CollectorMetadata(name="test_dz_1", country="DZ", category="test", entity_types=[])
        def collect(self): return []

    class TestUSCollector(MarketplaceCollector):
        metadata = CollectorMetadata(name="test_us_1", country="US", category="test", entity_types=[])
        def collect(self): return []

    CollectorRegistry.register(TestDZCollector())
    CollectorRegistry.register(TestUSCollector())

    dz_collectors = CollectorRegistry.list_by_country("DZ")
    us_collectors = CollectorRegistry.list_by_country("US")

    dz_names = [m.name for m in dz_collectors]
    us_names = [m.name for m in us_collectors]

    assert "test_dz_1" in dz_names
    assert "test_us_1" not in dz_names
    assert "test_us_1" in us_names


def test_registry_list_by_category():
    class TestNewsCollector(MarketplaceCollector):
        metadata = CollectorMetadata(name="test_news_1", country="DZ", category="news", entity_types=[])
        def collect(self): return []

    class TestJobsCollector(MarketplaceCollector):
        metadata = CollectorMetadata(name="test_jobs_1", country="DZ", category="jobs", entity_types=[])
        def collect(self): return []

    CollectorRegistry.register(TestNewsCollector())
    CollectorRegistry.register(TestJobsCollector())

    news = CollectorRegistry.list_by_category("news")
    jobs = CollectorRegistry.list_by_category("jobs")

    assert any(m.name == "test_news_1" for m in news)
    assert any(m.name == "test_jobs_1" for m in jobs)


def test_registry_list_by_entity_type():
    class TestCollector(MarketplaceCollector):
        metadata = CollectorMetadata(
            name="test_entity_1",
            country="DZ",
            category="test",
            entity_types=["product", "price"],
        )
        def collect(self): return []

    CollectorRegistry.register(TestCollector())

    product_collectors = CollectorRegistry.list_by_entity_type("product")
    price_collectors = CollectorRegistry.list_by_entity_type("price")
    company_collectors = CollectorRegistry.list_by_entity_type("company")

    assert any(m.name == "test_entity_1" for m in product_collectors)
    assert any(m.name == "test_entity_1" for m in price_collectors)
    assert not any(m.name == "test_entity_1" for m in company_collectors)


def test_registry_get_stats():
    stats = CollectorRegistry.get_stats()
    assert "total_collectors" in stats
    assert "by_country" in stats
    assert "by_category" in stats
    assert "by_health" in stats
    assert "requires_credentials" in stats


# ─── Health Monitor ────────────────────────────────────────────────────

def test_health_monitor_record_success():
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        monitor = CollectorHealthMonitor(db_path)

        monitor.record_success("test_collector", latency_ms=450, items_collected=25)

        health = monitor.get_health("test_collector")
        assert health.collector_name == "test_collector"
        assert health.total_calls == 1
        assert health.total_successes == 1
        assert health.total_items_collected == 25
        assert health.avg_latency_ms == 450
        assert health.status == "healthy"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_health_monitor_record_failure():
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        monitor = CollectorHealthMonitor(db_path)

        monitor.record_failure("test_collector", error="HTTP 500")

        health = monitor.get_health("test_collector")
        assert health.total_calls == 1
        assert health.total_failures == 1
        assert health.consecutive_failures == 1
        assert health.last_error == "HTTP 500"
        assert health.status in ("degraded", "unknown")  # 1 failure not enough for "down"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_health_monitor_status_transitions():
    """Status should transition: healthy → degraded → down as failures accumulate."""
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        monitor = CollectorHealthMonitor(db_path)

        # 5 consecutive failures → down
        for i in range(5):
            monitor.record_failure("test_col", f"error {i}")

        health = monitor.get_health("test_col")
        assert health.status == "down"
        assert health.consecutive_failures == 5

        # A success resets consecutive_failures
        monitor.record_success("test_col", latency_ms=100, items_collected=5)
        health = monitor.get_health("test_col")
        assert health.consecutive_failures == 0
        # success_rate is 1/6 = 0.167 — degraded (not enough successes yet, but no consecutive failures)
        assert health.status in ("down", "degraded")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_health_monitor_get_all_health():
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        monitor = CollectorHealthMonitor(db_path)

        monitor.record_success("collector_a", 100, 10)
        monitor.record_success("collector_b", 200, 20)

        all_health = monitor.get_all_health()
        assert "collector_a" in all_health
        assert "collector_b" in all_health
        assert all_health["collector_a"].total_items_collected == 10
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_health_monitor_get_stats():
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        monitor = CollectorHealthMonitor(db_path)

        monitor.record_success("a", 100, 10)
        monitor.record_success("b", 200, 20)
        monitor.record_failure("c", "error")

        stats = monitor.get_stats()
        assert stats["total_collectors_tracked"] == 3
        assert stats["total_items_collected_all_time"] == 30
        assert "by_status" in stats
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ─── Individual Collectors (metadata + instantiation) ─────────────────

def test_ouedkniss_collector_metadata():
    collector = OuedknissCollector()
    meta = collector.metadata
    assert meta.name == "ouedkniss"
    assert meta.country == "DZ"
    assert meta.category == "classifieds"
    assert "product" in meta.entity_types
    assert meta.reliability == 0.65


def test_ouedkniss_collector_instantiates_with_config():
    collector = OuedknissCollector({
        "categories": ["immobilier", "automobile"],
        "max_items": 20,
        "wilaya_filter": "DZ-16",
    })
    assert collector._categories == ["immobilier", "automobile"]
    assert collector._max_items == 20
    assert collector._wilaya_filter == "DZ-16"


def test_algeria_jobs_collector_metadata():
    collector = AlgerianJobBoardCollector()
    meta = collector.metadata
    assert meta.name == "algeria_jobs"
    assert meta.country == "DZ"
    assert meta.category == "jobs"
    assert "job" in meta.entity_types
    assert meta.reliability == 0.70


def test_algeria_jobs_collector_has_default_sources():
    collector = AlgerianJobBoardCollector()
    assert len(collector._sources) >= 1
    assert all("url" in s for s in collector._sources)


def test_algeria_forum_collector_metadata():
    collector = AlgerianForumCollector()
    meta = collector.metadata
    assert meta.name == "algeria_forums"
    assert meta.country == "DZ"
    assert meta.category == "forum"
    assert "discussion" in meta.entity_types


def test_algeria_gov_collector_metadata():
    collector = AlgerianGovCollector()
    meta = collector.metadata
    assert meta.name == "algeria_gov"
    assert meta.country == "DZ"
    assert meta.category == "government"
    assert "statistic" in meta.entity_types
    assert meta.reliability == 0.90  # official sources


def test_marketplace_rss_collector_metadata():
    collector = MarketplaceRSSCollector()
    meta = collector.metadata
    assert meta.name == "rss"
    assert meta.category == "news"
    assert "article" in meta.entity_types


def test_marketplace_rss_collector_with_feeds():
    collector = MarketplaceRSSCollector({
        "feeds": [
            {"url": "https://example.com/feed.xml", "name": "Example"},
        ],
        "max_items_per_feed": 10,
    })
    assert len(collector._feeds) == 1
    assert collector._max_items == 10


# ─── Registration + Collect ────────────────────────────────────────────

def test_all_algerian_collectors_register():
    """Verify all 4 Algerian collectors can be registered."""
    CollectorRegistry.register(OuedknissCollector())
    CollectorRegistry.register(AlgerianJobBoardCollector())
    CollectorRegistry.register(AlgerianForumCollector())
    CollectorRegistry.register(AlgerianGovCollector())

    dz_collectors = CollectorRegistry.list_by_country("DZ")
    dz_names = {m.name for m in dz_collectors}

    assert "ouedkniss" in dz_names
    assert "algeria_jobs" in dz_names
    assert "algeria_forums" in dz_names
    assert "algeria_gov" in dz_names


def test_collector_collect_returns_list():
    """Even on failure, collect() should return a list (possibly empty)."""
    # Ouedkniss with bad config should not crash, just return empty
    collector = OuedknissCollector({"categories": ["nonexistent_category"]})
    items = collector.collect()
    assert isinstance(items, list)


def test_collector_has_required_credentials_check():
    """Collectors without required_credentials should pass credential check."""
    collector = OuedknissCollector()
    assert collector.has_required_credentials() is True


# ─── MarketplaceCollector ABC ──────────────────────────────────────────

def test_marketplace_collector_is_abstract():
    """Cannot instantiate MarketplaceCollector directly."""
    import pytest
    with pytest.raises(TypeError):
        MarketplaceCollector()


def test_custom_collector_subclass_works():
    """Anyone can subclass MarketplaceCollector and it works."""
    class MyCustomCollector(MarketplaceCollector):
        metadata = CollectorMetadata(
            name="my_custom_test_collector",
            country="DZ",
            category="custom",
            entity_types=["custom_entity"],
            description="A custom collector for testing",
            reliability=0.80,
        )

        def collect(self):
            return [RawItem.create(
                source="my_custom_test_collector",
                source_name="My Custom",
                title="Test item",
                url="http://test.com/1",
            )]

    collector = MyCustomCollector()
    CollectorRegistry.register(collector)

    # Should be discoverable
    custom = CollectorRegistry.get("my_custom_test_collector")
    assert custom is not None

    # Should produce items
    items = collector.collect()
    assert len(items) == 1
    assert items[0].title == "Test item"

    # Should have correct metadata
    assert collector.metadata.reliability == 0.80
