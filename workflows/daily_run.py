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
        from collectors.hackernews_collector import HackerNewsCollector
        from collectors.github_issues_collector import GitHubIssuesCollector
        from collectors.producthunt_collector import ProductHuntCollector
        from collectors.g2_collector import G2Collector
        from collectors.jobboard_collector import JobBoardCollector

        reddit_cfg = collectors_config.get("reddit", {})
        if reddit_cfg.get("enabled", False):
            self._container.register_collector("reddit", RedditCollector(reddit_cfg, retry_config))

        rss_cfg = collectors_config.get("rss", {})
        if rss_cfg.get("enabled", False):
            self._container.register_collector("rss", RSSCollector(rss_cfg, retry_config))

        gn_cfg = collectors_config.get("google_news", {})
        if gn_cfg.get("enabled", False):
            self._container.register_collector("google_news", GoogleNewsCollector(gn_cfg, retry_config))

        hn_cfg = collectors_config.get("hacker_news", {})
        if hn_cfg.get("enabled", False):
            self._container.register_collector("hacker_news", HackerNewsCollector(hn_cfg, retry_config))

        gh_cfg = collectors_config.get("github_issues", {})
        if gh_cfg.get("enabled", False):
            self._container.register_collector("github_issues", GitHubIssuesCollector(gh_cfg, retry_config))

        ph_cfg = collectors_config.get("product_hunt", {})
        if ph_cfg.get("enabled", False):
            self._container.register_collector("product_hunt", ProductHuntCollector(ph_cfg, retry_config))

        g2_cfg = collectors_config.get("g2", {})
        if g2_cfg.get("enabled", False):
            self._container.register_collector("g2", G2Collector(g2_cfg, retry_config))

        jb_cfg = collectors_config.get("job_boards", {})
        if jb_cfg.get("enabled", False):
            self._container.register_collector("job_boards", JobBoardCollector(jb_cfg, retry_config))

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
        from processors.entity_graph import EntityGraphProcessor
        from processors.scoring import ScoringProcessor

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

        # 9. Entity graph builder
        graph_cfg = processors_config.get("entity_graph", {})
        if graph_cfg.get("enabled", True):
            self._container.register_processor("entity_graph", EntityGraphProcessor(graph_cfg))

        # 10. Scoring engine
        scoring_cfg = processors_config.get("scoring", {})
        if scoring_cfg.get("enabled", True):
            self._container.register_processor("scoring", ScoringProcessor(scoring_cfg))

        # ─── Storage ───────────────────────────────────────────────────
"""
Main workflow orchestrator — ties collectors, processors, storage, and reports together.

Phase 2: Intelligence pipeline
  Collect → Dedup → Enrich → Entity Extraction → Competitor Detection →
  Pain-Point Extraction → Buying-Signal Detection → Topic Clustering →
  Trend Detection → Store → Generate Intelligence Report
"""
