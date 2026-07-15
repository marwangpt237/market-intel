"""
Main workflow orchestrator — ties collectors, processors, storage, and reports together.

Phase 2: Intelligence pipeline
  Collect → Dedup → Enrich → Entity Extraction → Competitor Detection →
  Pain-Point Extraction → Buying-Signal Detection → Topic Clustering →
  Trend Detection → Store → Generate Intelligence Report
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from collections import Counter
from core.config_loader import Config
from core.container import Container
from core.logger import get_logger, setup_logging
from core.models import RawItem, ProcessedItem


class DailyRun:
    """Orchestrates a single intelligence collection + processing + report run."""

    def __init__(self, config: Config):
        self._config = config
        self._logger = get_logger("workflow")
        self._container = Container(config.to_dict())
        self._run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self._setup_components()

    def _setup_components(self) -> None:
        """Register all enabled components in the container."""
        collectors_config = self._config.collectors
        retry_config = self._config.retry

        # ─── Collectors ────────────────────────────────────────────────
        from collectors.reddit_collector import RedditCollector
        from collectors.rss_collector import RSSCollector
        from collectors.google_news_collector import GoogleNewsCollector

        reddit_cfg = collectors_config.get("reddit", {})
        if reddit_cfg.get("enabled", False):
            self._container.register_collector("reddit", RedditCollector(reddit_cfg, retry_config))

        rss_cfg = collectors_config.get("rss", {})
        if rss_cfg.get("enabled", False):
            self._container.register_collector("rss", RSSCollector(rss_cfg, retry_config))

        gn_cfg = collectors_config.get("google_news", {})
        if gn_cfg.get("enabled", False):
            self._container.register_collector("google_news", GoogleNewsCollector(gn_cfg, retry_config))

        # ─── Processors (ordered pipeline) ─────────────────────────────
        processors_config = self._config.processors

        from processors.similarity_dedup import SimilarityDedupProcessor
        from processors.enrich import EnrichProcessor
        from processors.entity_extraction import EntityExtractionProcessor
        from processors.competitor_detection import CompetitorDetectionProcessor
        from processors.pain_point_extraction import PainPointExtractionProcessor
        from processors.buying_signal import BuyingSignalProcessor
        from processors.topic_clustering import TopicClusteringProcessor
        from processors.trend_detection import TrendDetectionProcessor

        # 1. Dedup (similarity-based)
        dedup_cfg = processors_config.get("similarity_dedup", processors_config.get("dedup", {}))
        if dedup_cfg.get("enabled", True):
            self._container.register_processor("similarity_dedup", SimilarityDedupProcessor(dedup_cfg))

        # 2. Enrich (sentiment, keywords, read time)
        enrich_cfg = processors_config.get("enrich", {})
        if enrich_cfg.get("enabled", True):
            self._container.register_processor("enrich", EnrichProcessor(enrich_cfg))

        # 3. Entity extraction (companies, products, people)
        entity_cfg = processors_config.get("entity_extraction", {})
        if entity_cfg.get("enabled", True):
            self._container.register_processor("entity_extraction", EntityExtractionProcessor(entity_cfg))

        # 4. Competitor detection
        competitor_cfg = processors_config.get("competitor_detection", {})
        if competitor_cfg.get("enabled", True):
            self._container.register_processor("competitor_detection", CompetitorDetectionProcessor(competitor_cfg))

        # 5. Pain-point extraction
        pain_cfg = processors_config.get("pain_point_extraction", {})
        if pain_cfg.get("enabled", True):
            self._container.register_processor("pain_point_extraction", PainPointExtractionProcessor(pain_cfg))

        # 6. Buying-signal detection
        buying_cfg = processors_config.get("buying_signal_detection", {})
        if buying_cfg.get("enabled", True):
            self._container.register_processor("buying_signal_detection", BuyingSignalProcessor(buying_cfg))

        # 7. Topic clustering
        cluster_cfg = processors_config.get("topic_clustering", {})
        if cluster_cfg.get("enabled", True):
            self._container.register_processor("topic_clustering", TopicClusteringProcessor(cluster_cfg))

        # 8. Trend detection (needs historical data)
        trend_cfg = processors_config.get("trend_detection", {})
        if trend_cfg.get("enabled", True):
            trend_processor = TrendDetectionProcessor(trend_cfg)
            # Load historical keyword counts for comparison
            historical_counts = self._load_historical_keywords()
            trend_processor.set_history(historical_counts)
            self._container.register_processor("trend_detection", trend_processor)

        # ─── Storage ───────────────────────────────────────────────────
        storage_config = self._config.storage
        from storage.json_store import JSONStorage
        self._container.set_storage(JSONStorage(storage_config))

        # ─── Reports ───────────────────────────────────────────────────
        reports_config = self._config.reports
        intel_cfg = reports_config.get("intelligence", reports_config.get("markdown", {}))
        if intel_cfg.get("enabled", True):
            from reports.intelligence_report import IntelligenceReportGenerator
            self._container.set_report_generator(IntelligenceReportGenerator(intel_cfg))

    def _load_historical_keywords(self) -> dict[str, int]:
        """Load keyword frequencies from recent storage for trend comparison."""
        try:
            storage = self._container.get_storage()
            recent_items = storage.load_recent(days=7)
            keyword_counts: Counter = Counter()
            for item in recent_items:
                for kw in item.get("keywords", []):
                    keyword_counts[kw] += 1
            # Return average per day (7 days of data)
            return {kw: max(1, count // 7) for kw, count in keyword_counts.items()}
        except Exception:
            return {}

    def run(self) -> dict:
        """Execute the full intelligence pipeline. Returns a summary dict."""
        self._logger.info(f"Starting intelligence run {self._run_id}")
        start_time = datetime.now(timezone.utc)

        # Phase 1: Collect
        self._logger.info("Phase 1: Collection")
        raw_items: list[RawItem] = []
        for name, collector in self._container.get_collectors().items():
            items = collector.collect()
            raw_items.extend(items)
        self._logger.info(f"Collection complete: {len(raw_items)} raw items")

        # Phase 2: Process (ordered pipeline)
        self._logger.info("Phase 2: Intelligence Processing")
        processed_items = [ProcessedItem.from_raw(raw) for raw in raw_items]

        for name, processor in self._container.get_processors().items():
            processed_items = processor.process(processed_items)

        self._logger.info(f"Processing complete: {len(processed_items)} processed items")

        # Phase 3: Store
        self._logger.info("Phase 3: Storage")
        item_dicts = [item.to_dict() for item in processed_items]
        storage_path = self._container.get_storage().save(item_dicts, self._run_id)

        # Phase 4: Report
        self._logger.info("Phase 4: Intelligence Report")
        report_path = ""
        report_gen = self._container.get_report_generator()
        if report_gen:
            report_path = report_gen.generate(processed_items, self._run_id)

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        # Build summary
        pain_count = sum(len(item.metadata.get("pain_points", [])) for item in processed_items)
        competitor_count = sum(len(item.metadata.get("competitor_mentions", [])) for item in processed_items)
        buying_count = len([item for item in processed_items if item.metadata.get("buying_signals")])
        entity_count = sum(len(item.metadata.get("entities", {}).get("companies", [])) for item in processed_items)

        summary = {
            "run_id": self._run_id,
            "started_at": start_time.isoformat(),
            "completed_at": end_time.isoformat(),
            "duration_seconds": round(duration, 2),
            "raw_items_collected": len(raw_items),
            "processed_items": len(processed_items),
            "pain_points_detected": pain_count,
            "competitor_mentions": competitor_count,
            "buying_signals": buying_count,
            "entities_extracted": entity_count,
            "collectors_used": list(self._container.get_collectors().keys()),
            "processors_used": list(self._container.get_processors().keys()),
            "storage_path": storage_path,
            "report_path": report_path,
            "status": "success" if processed_items else "no_data",
        }

        self._logger.info(f"Intelligence run complete in {duration:.1f}s", extra=summary)
        return summary
