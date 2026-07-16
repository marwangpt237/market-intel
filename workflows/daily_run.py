"""
Main workflow orchestrator — ties collectors, processors, storage, and reports together.

Phase 3 closed-loop pipeline:
  Collect → Dedup → Enrich → Entity Extraction → Competitor Detection →
  Pain-Point Extraction → Buying-Signal Detection → Topic Clustering →
  Trend Detection → Entity Graph → Scoring → Store → Generate Reports

Phase 4 closes the loop:
  ... → Scoring → Decision Engine → Execution Engine →
       Analytics Engine → Learning Engine → Generate Decision Report

Decision → Execution → Analytics → Learning → (adjust weights) → next run
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

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
        from processors.source_authority import SourceAuthorityProcessor
        from processors.entity_extraction import EntityExtractionProcessor
        from processors.competitor_detection import CompetitorDetectionProcessor
        from processors.pain_point_extraction import PainPointExtractionProcessor
        from processors.buying_signal import BuyingSignalProcessor
        from processors.topic_clustering import TopicClusteringProcessor
        from processors.trend_detection import TrendDetectionProcessor
        from processors.entity_graph import EntityGraphProcessor
        from processors.scoring import ScoringProcessor
        from processors.domain_processor import DomainProcessor
        from processors.decision_engine import DecisionEngine
        from processors.false_positive_filter import FalsePositiveFilter
        from processors.strategy_engine import StrategyEngine
        from processors.execution_engine import ExecutionEngine
        from processors.analytics_engine import AnalyticsEngine
        from processors.learning_engine import LearningEngine

        # 0. Source authority (Phase 5) — filter low-quality + non-English items early
        source_auth_cfg = processors_config.get("source_authority", {})
        if source_auth_cfg.get("enabled", True):
            self._container.register_processor("source_authority", SourceAuthorityProcessor(source_auth_cfg))

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
            # Learning engine may have adjusted weights — load them
            learning_weights = self._load_learning_weights()
            merged_scoring_cfg = {**scoring_cfg, **{"weights": learning_weights}}
            self._container.register_processor("scoring", ScoringProcessor(merged_scoring_cfg))

        # 10b. Domain processor (Phase 5) — tags items with SaaS / Cybersecurity / Ecommerce signals
        domain_cfg = processors_config.get("domain", {})
        if domain_cfg.get("enabled", True):
            self._container.register_processor("domain", DomainProcessor(domain_cfg))

        # 11. Decision engine (Phase 4)
        decision_cfg = processors_config.get("decision_engine", {})
        if decision_cfg.get("enabled", True):
            self._container.register_processor("decision_engine", DecisionEngine(decision_cfg))

        # 11b. False positive filter (Phase 5) — removes mega-corp / generic / weak-evidence decisions
        fpf_cfg = processors_config.get("false_positive_filter", {})
        if fpf_cfg.get("enabled", True):
            self._container.register_processor("false_positive_filter", FalsePositiveFilter(fpf_cfg))

        # 11c. Strategy engine (Phase 5 + Phase 6) — knapsack optimization with learned ROI
        strategy_cfg = processors_config.get("strategy_engine", {})
        if strategy_cfg.get("enabled", True):
            # Pass historical performance data + storage config (for LearnedScorer)
            historical_perf = self._load_historical_performance()
            storage_cfg_for_strategy = self._config.storage
            merged_strategy_cfg = {
                **strategy_cfg,
                "historical_performance": historical_perf,
                "storage": storage_cfg_for_strategy,
            }
            self._container.register_processor("strategy_engine", StrategyEngine(merged_strategy_cfg))

        # 12. Execution engine (Phase 4)
        execution_cfg = processors_config.get("execution_engine", {})
        if execution_cfg.get("enabled", True):
            self._container.register_processor("execution_engine", ExecutionEngine(execution_cfg))

        # 13. Analytics engine (Phase 4) — records executed actions in SQLite
        analytics_cfg = processors_config.get("analytics_engine", {})
        if analytics_cfg.get("enabled", True):
            storage_cfg = self._config.storage
            self._container.register_processor(
                "analytics_engine",
                AnalyticsEngine({**analytics_cfg, **{"storage": storage_cfg}})
            )

        # 14. Learning engine (Phase 4) — adjusts weights for next run
        learning_cfg = processors_config.get("learning_engine", {})
        if learning_cfg.get("enabled", True):
            storage_cfg = self._config.storage
            self._container.register_processor(
                "learning_engine",
                LearningEngine({**learning_cfg, **{"storage": storage_cfg}})
            )

        # ─── Country Packs (Phase 7) — regional intelligence layer ────────
        country_cfg = self._config.to_dict().get("country_pack", {})
        if country_cfg.get("enabled"):
            country_name = country_cfg.get("name", "algeria")
            try:
                if country_name == "algeria":
                    from country_packs.algeria.pack import AlgeriaPack
                from country_packs.base import get_country_pack
                pack = get_country_pack(country_name, country_cfg.get("config", {}))
                if pack:
                    for processor in pack.get_processors():
                        self._container.register_processor(f"country_{processor.name}", processor)
                    self._logger.info(f"Country pack '{country_name}' loaded: {len(pack.get_processors())} processors")
            except Exception as e:
                self._logger.error(f"Country pack '{country_name}' failed to load: {e}", exc_info=True)

        # ─── Vertical Packs (Phase 7) — use-case intelligence layer ───────
        vertical_cfg = self._config.to_dict().get("vertical_pack", {})
        if vertical_cfg.get("enabled"):
            vertical_name = vertical_cfg.get("name", "ecommerce")
            try:
                if vertical_name == "ecommerce":
                    from vertical_packs.ecommerce.radar import EcommerceVerticalPack
                from vertical_packs.base import get_vertical_pack
                pack = get_vertical_pack(vertical_name, vertical_cfg.get("config", {}))
                if pack:
                    for processor in pack.get_processors():
                        self._container.register_processor(f"vertical_{processor.name}", processor)
                    self._logger.info(f"Vertical pack '{vertical_name}' loaded: {len(pack.get_processors())} processors")
            except Exception as e:
                self._logger.error(f"Vertical pack '{vertical_name}' failed to load: {e}", exc_info=True)

        # ─── Validation Engine (Phase 8) — knowledge base integrity ──────
        validation_cfg = processors_config.get("validation_engine", {})
        if validation_cfg.get("enabled", False):  # opt-in via config
            try:
                from validation.engine import ValidationEngine
                storage_cfg = self._config.storage
                merged_validation_cfg = {
                    **validation_cfg,
                    "storage": storage_cfg,
                }
                self._container.register_processor("validation_engine", ValidationEngine(merged_validation_cfg))
                self._logger.info("Validation engine loaded (Phase 8)")
            except Exception as e:
                self._logger.error(f"Validation engine failed to load: {e}", exc_info=True)

        # ─── Acquisition Engine (Phase 9) — autonomous research planner ──
        acquisition_cfg = processors_config.get("acquisition_engine", {})
        if acquisition_cfg.get("enabled", False):  # opt-in via config
            try:
                from acquisition.engine import AcquisitionEngine
                self._container.register_processor("acquisition_engine", AcquisitionEngine(acquisition_cfg))
                self._logger.info("Acquisition engine loaded (Phase 9)")
            except Exception as e:
                self._logger.error(f"Acquisition engine failed to load: {e}", exc_info=True)

        # ─── Storage ───────────────────────────────────────────────────
        storage_cfg = self._config.storage
        storage_type = storage_cfg.get("type", "json")
        if storage_type == "sqlite":
            from storage.sqlite_store import SQLiteStorage
            self._container.set_storage(SQLiteStorage(storage_cfg))
        else:
            from storage.json_store import JSONStorage
            self._container.set_storage(JSONStorage(storage_cfg))

        # ─── Reports ───────────────────────────────────────────────────
        reports_cfg = self._config.reports
        intel_cfg = reports_cfg.get("intelligence", {})
        if intel_cfg.get("enabled", True):
            from reports.intelligence_report import IntelligenceReportGenerator
            self._container.set_report_generator(IntelligenceReportGenerator(intel_cfg))

    def _load_historical_keywords(self) -> dict[str, int]:
        """Load keyword history from SQLite for trend comparison."""
        try:
            storage_cfg = self._config.storage
            if storage_cfg.get("type") != "sqlite":
                return {}
            from storage.sqlite_store import SQLiteStorage
            storage = SQLiteStorage(storage_cfg)
            return storage.load_keyword_history(days=30)
        except Exception as e:
            self._logger.warning(f"Could not load historical keywords: {e}")
            return {}

    def _load_learning_weights(self) -> dict:
        """Load learning-adjusted weights from data/learning_weights.json."""
        try:
            weights_path = Path(self._config.storage.get("path", "data/market_intel.db")).parent / "learning_weights.json"
            if weights_path.exists():
                with open(weights_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            self._logger.warning(f"Could not load learning weights: {e}")
        return {}

    def _load_historical_performance(self) -> dict:
        """Load per-(decision_type, priority) historical outcome data from SQLite.

        Used by Strategy Engine to give ROI bonus to actions whose buckets
        have historically outperformed baseline.
        """
        try:
            storage_cfg = self._config.storage
            if storage_cfg.get("type") != "sqlite":
                return {}
            from storage.sqlite_store import SQLiteStorage
            import sqlite3
            storage = SQLiteStorage(storage_cfg)
            db_path = storage._db_path
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT decision_type, priority,
                              SUM(clicks) AS clicks, SUM(signups) AS signups,
                              SUM(conversions) AS conversions, SUM(revenue) AS revenue,
                              COUNT(*) AS count
                       FROM actions
                       WHERE status IN ('sent', 'published')
                       GROUP BY decision_type, priority"""
                ).fetchall()
            if not rows:
                return {}
            # Compute overall baseline
            total_outcome = 0
            total_count = 0
            buckets = []
            for r in rows:
                outcome = (r["signups"] or 0) * 5 + (r["conversions"] or 0) * 25 + float(r["revenue"] or 0) * 0.1
                avg = outcome / r["count"] if r["count"] else 0
                buckets.append((r["decision_type"], r["priority"], avg, r["count"]))
                total_outcome += outcome
                total_count += r["count"]
            baseline = total_outcome / total_count if total_count else 0
            result = {}
            for dtype, priority, avg, count in buckets:
                result[f"{dtype}_{priority}"] = {
                    "avg_outcome": avg,
                    "baseline_outcome": baseline,
                    "sample_size": count,
                }
            return result
        except Exception as e:
            self._logger.warning(f"Could not load historical performance: {e}")
            return {}

    def run(self) -> dict:
        """Execute the full pipeline. Returns a summary dict for logging."""
        self._logger.info(f"Starting run {self._run_id}")

        # 1. Collect
        collectors = self._container.get_collectors()
        raw_items: list[RawItem] = []
        collector_stats: dict[str, int] = {}
        for name, collector in collectors.items():
            try:
                items = collector.collect()
                raw_items.extend(items)
                collector_stats[name] = len(items)
                self._logger.info(f"Collector '{name}': {len(items)} items")
            except Exception as e:
                self._logger.error(f"Collector '{name}' failed: {e}", exc_info=True)
                collector_stats[name] = 0

        if not raw_items:
            self._logger.warning("No items collected — aborting run")
            return {
                "run_id": self._run_id,
                "status": "no_data",
                "collectors": collector_stats,
            }

        # 2. Convert raw → processed
        processed_items = [ProcessedItem.from_raw(raw) for raw in raw_items]
        self._logger.info(f"Total items to process: {len(processed_items)}")

        # 3. Run processors in order
        processors = self._container.get_processors()
        for name, processor in processors.items():
            try:
                processed_items = processor.process(processed_items)
                self._logger.info(f"Processor '{name}': {len(processed_items)} items after")
            except Exception as e:
                self._logger.error(f"Processor '{name}' failed: {e}", exc_info=True)

        # 4. Storage
        try:
            storage = self._container.get_storage()
            storage.save([self._processed_to_dict(item) for item in processed_items], self._run_id)
        except Exception as e:
            self._logger.error(f"Storage failed: {e}", exc_info=True)

        # 5. Reports
        try:
            report_gen = self._container.get_report_generator()
            report_path = report_gen.generate(processed_items, self._run_id)
            self._logger.info(f"Report generated: {report_path}")
        except Exception as e:
            self._logger.error(f"Report generation failed: {e}", exc_info=True)
            report_path = None

        # 6. Decision report (Phase 4)
        decision_report_path = None
        try:
            from reports.decision_report import DecisionReportGenerator
            dec_cfg = self._config.reports.get("decisions", {"enabled": True, "output_path": "reports/"})
            if dec_cfg.get("enabled", True):
                dec_gen = DecisionReportGenerator(dec_cfg)
                decision_report_path = dec_gen.generate(processed_items, self._run_id)
                self._logger.info(f"Decision report generated: {decision_report_path}")
        except Exception as e:
            self._logger.error(f"Decision report failed: {e}", exc_info=True)

        # 6b. Strategy report (Phase 5) — optimal plan under constraints
        strategy_report_path = None
        try:
            from reports.strategy_report import StrategyReportGenerator
            strat_cfg = self._config.reports.get("strategy", {"enabled": True, "output_path": "reports/"})
            if strat_cfg.get("enabled", True):
                strat_gen = StrategyReportGenerator(strat_cfg)
                strategy_report_path = strat_gen.generate(processed_items, self._run_id)
                self._logger.info(f"Strategy report generated: {strategy_report_path}")
        except Exception as e:
            self._logger.error(f"Strategy report failed: {e}", exc_info=True)

        # 6c. Learning report (Phase 6) — feature weight evolution + model stats
        learning_report_path = None
        try:
            from reports.learning_report import LearningReportGenerator
            learn_cfg = self._config.reports.get("learning", {"enabled": True, "output_path": "reports/"})
            if learn_cfg.get("enabled", True):
                learn_gen = LearningReportGenerator(learn_cfg)
                learning_report_path = learn_gen.generate(processed_items, self._run_id)
                self._logger.info(f"Learning report generated: {learning_report_path}")
        except Exception as e:
            self._logger.error(f"Learning report failed: {e}", exc_info=True)

        # 6d. Client acquisition report (optional — only if client_acq domain module ran)
        client_acq_report_path = None
        try:
            from reports.client_acq_report import ClientAcquisitionReportGenerator
            ca_cfg = self._config.reports.get("client_acq", {"enabled": False, "output_path": "reports/"})
            if ca_cfg.get("enabled", False):
                # Only generate if at least one item has client_acquisition domain signals
                has_client_acq_signals = any(
                    "client_acquisition" in (i.metadata.get("domain_signals") or {})
                    for i in processed_items
                )
                if has_client_acq_signals:
                    ca_gen = ClientAcquisitionReportGenerator(ca_cfg)
                    client_acq_report_path = ca_gen.generate(processed_items, self._run_id)
                    self._logger.info(f"Client acquisition report generated: {client_acq_report_path}")
                else:
                    self._logger.info("Client acquisition report enabled but no client_acq signals detected — skipping")
        except Exception as e:
            self._logger.error(f"Client acquisition report failed: {e}", exc_info=True)

        # 6e. Product Intelligence report (Phase 7 — Algeria Pack + E-commerce Radar)
        product_intel_report_path = None
        try:
            from reports.product_intelligence_report import ProductIntelligenceReportGenerator
            pi_cfg = self._config.reports.get("product_intelligence", {"enabled": False, "output_path": "reports/"})
            if pi_cfg.get("enabled", False):
                has_product_intel = any("_product_intelligence" in i.metadata for i in processed_items)
                if has_product_intel:
                    pi_gen = ProductIntelligenceReportGenerator(pi_cfg)
                    product_intel_report_path = pi_gen.generate(processed_items, self._run_id)
                    self._logger.info(f"Product intelligence report generated: {product_intel_report_path}")
                else:
                    self._logger.info("Product intelligence report enabled but no _product_intelligence data — skipping")
        except Exception as e:
            self._logger.error(f"Product intelligence report failed: {e}", exc_info=True)

        # 6f. Validation report (Phase 8 — Evidence Validation Engine)
        validation_report_path = None
        try:
            from reports.validation_report import ValidationReportGenerator
            val_cfg = self._config.reports.get("validation", {"enabled": False, "output_path": "reports/"})
            if val_cfg.get("enabled", False):
                has_validation_data = any("_validation" in i.metadata for i in processed_items)
                if has_validation_data:
                    val_gen = ValidationReportGenerator(val_cfg)
                    validation_report_path = val_gen.generate(processed_items, self._run_id)
                    self._logger.info(f"Validation report generated: {validation_report_path}")
                else:
                    self._logger.info("Validation report enabled but no _validation data — skipping")
        except Exception as e:
            self._logger.error(f"Validation report failed: {e}", exc_info=True)

        # 6g. Acquisition report (Phase 9 — Autonomous Research Planner)
        acquisition_report_path = None
        try:
            from reports.acquisition_report import AcquisitionReportGenerator
            acq_cfg = self._config.reports.get("acquisition", {"enabled": False, "output_path": "reports/"})
            if acq_cfg.get("enabled", False):
                has_acquisition_data = any("_acquisition" in i.metadata for i in processed_items)
                if has_acquisition_data:
                    acq_gen = AcquisitionReportGenerator(acq_cfg)
                    acquisition_report_path = acq_gen.generate(processed_items, self._run_id)
                    self._logger.info(f"Acquisition report generated: {acquisition_report_path}")
                else:
                    self._logger.info("Acquisition report enabled but no _acquisition data — skipping")
        except Exception as e:
            self._logger.error(f"Acquisition report failed: {e}", exc_info=True)

        # 7. Build summary
        scores = processed_items[0].metadata.get("_scores", {}) if processed_items else {}
        decisions = processed_items[0].metadata.get("_decisions", {}) if processed_items else {}
        executions = processed_items[0].metadata.get("_executions", {}) if processed_items else {}
        learning = processed_items[0].metadata.get("_learning", {}) if processed_items else {}
        strategy = processed_items[0].metadata.get("_strategy", {}) if processed_items else {}

        summary = {
            "run_id": self._run_id,
            "status": "ok",
            "total_items": len(processed_items),
            "collectors": collector_stats,
            "companies_scored": len(scores.get("company_scores", [])),
            "topics_scored": len(scores.get("topic_scores", [])),
            "insights": len(scores.get("insights", [])),
            "decisions": len(decisions.get("decisions", [])) if isinstance(decisions, dict) else 0,
            "filtered": sum(decisions.get("filter_counts", {}).values()) if isinstance(decisions, dict) else 0,
            "actions_selected": len(strategy.get("selected", [])) if isinstance(strategy, dict) else 0,
            "actions_executed": len(executions.get("artifacts", [])) if isinstance(executions, dict) else 0,
            "learning_adjustments": len(learning.get("weight_adjustments", [])) if isinstance(learning, dict) else 0,
            "projected_roi": strategy.get("projected", {}).get("total_roi", 0) if isinstance(strategy, dict) else 0,
            "report_path": report_path,
            "decision_report_path": decision_report_path,
            "strategy_report_path": strategy_report_path,
            "learning_report_path": learning_report_path,
            "client_acq_report_path": client_acq_report_path,
            "product_intelligence_report_path": product_intel_report_path,
            "validation_report_path": validation_report_path,
            "acquisition_report_path": acquisition_report_path,
        }

        self._logger.info(f"Run complete: {summary}")
        return summary

    @staticmethod
    def _processed_to_dict(item: ProcessedItem) -> dict:
        """Convert ProcessedItem to a dict for storage."""
        return {
            "id": item.id,
            "source": item.source,
            "source_name": item.source_name,
            "title": item.title,
            "url": item.url,
            "body": item.body,
            "author": item.author,
            "published_at": item.published_at,
            "collected_at": item.collected_at,
            "score": item.score,
            "tags": item.tags,
            "metadata": item.metadata,
            "sentiment": item.metadata.get("sentiment", "neutral"),
            "keywords": item.metadata.get("keywords", []),
            "read_time_minutes": item.metadata.get("read_time_minutes", 0),
            "dedup_key": item.metadata.get("dedup_key", ""),
            "cluster_id": item.metadata.get("cluster_id"),
            "cluster_label": item.metadata.get("cluster_label"),
            "trend": item.metadata.get("trend", "stable"),
            "buying_intent": item.metadata.get("buying_intent", 0.0),
            "processed_at": item.processed_at,
        }
