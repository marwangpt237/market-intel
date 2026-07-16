"""
Collector Marketplace — standard interface for all collectors.

Anyone can drop a new collector into the platform without modifying the
core engine. The collector declares its metadata (name, country, category,
entity types, rate limits, reliability, cost, required credentials,
health status) and the marketplace handles registration, health monitoring,
and discovery.

Architecture:

  CollectorMetadata (dataclass)
    ├── name: str
    ├── country: str (ISO code: DZ, MA, TN, US, FR, ...)
    ├── category: str (news, classifieds, jobs, forum, government, social, ...)
    ├── entity_types: list[str] (product, company, person, job, ...)
    ├── rate_limit_per_hour: int
    ├── reliability: float (0-1, used by TrustLayer)
    ├── cost_per_call: float (API credits, USD, etc.)
    ├── required_credentials: list[str] (env var names)
    ├── health_status: str (healthy, degraded, down, unknown)
    ├── description: str
    └── tags: list[str]

  MarketplaceCollector (ABC)
    ├── metadata: CollectorMetadata
    ├── collect() → list[RawItem]
    ├── health_check() → CollectorHealth
    └── get_metadata() → CollectorMetadata

  CollectorRegistry
    ├── register(collector)
    ├── get(name) → collector
    ├── list_by_country(country)
    ├── list_by_category(category)
    ├── list_by_entity_type(entity_type)
    └── list_all() → list[CollectorMetadata]

  CollectorHealthMonitor
    ├── record_success(collector_name, latency_ms, items_collected)
    ├── record_failure(collector_name, error)
    ├── get_health(collector_name) → CollectorHealth
    └── get_all_health() → dict[name, CollectorHealth]
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any
from core.logger import get_logger
from core.models import RawItem


@dataclass
class CollectorMetadata:
    """Standard metadata for every collector in the marketplace."""
    name: str                                    # unique identifier (e.g. "ouedkniss")
    country: str                                 # ISO code: DZ, MA, TN, US, FR, etc.
    category: str                                # news, classifieds, jobs, forum, government, social, marketplace
    entity_types: list[str]                      # what entity types this collector produces
    description: str = ""                        # human-readable description
    rate_limit_per_hour: int = 60                # max requests per hour
    reliability: float = 0.70                    # 0-1, used by TrustLayer
    cost_per_call: float = 0.0                   # API credits / USD per call
    required_credentials: list[str] = field(default_factory=list)  # env var names
    tags: list[str] = field(default_factory=list)
    health_status: str = "unknown"               # healthy, degraded, down, unknown

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CollectorHealth:
    """Health metrics for a collector."""
    collector_name: str
    status: str = "unknown"                      # healthy, degraded, down, unknown
    last_success: str | None = None              # ISO timestamp
    last_failure: str | None = None
    consecutive_failures: int = 0
    total_calls: int = 0
    total_successes: int = 0
    total_failures: int = 0
    total_items_collected: int = 0
    avg_latency_ms: float = 0.0
    last_error: str | None = None
    success_rate: float = 0.0                    # total_successes / total_calls
    last_health_check: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def update_success_rate(self) -> None:
        if self.total_calls > 0:
            self.success_rate = self.total_successes / self.total_calls
        else:
            self.success_rate = 0.0


class MarketplaceCollector(ABC):
    """Base class for all marketplace collectors.

    To add a new collector:
      1. Subclass MarketplaceCollector
      2. Set the `metadata` class attribute (CollectorMetadata)
      3. Implement collect() → list[RawItem]
      4. Optionally override health_check() for custom health logic
      5. Register: CollectorRegistry.register(MyCollector())

    The collector will then be:
      - Discoverable via CollectorRegistry.list_by_country/category/entity_type
      - Health-monitored by CollectorHealthMonitor
      - Trust-weighted by TrustLayer (using metadata.reliability)
      - Available in the Collector Registry Report
    """
    metadata: CollectorMetadata = CollectorMetadata(
        name="base",
        country="XX",
        category="unknown",
        entity_types=[],
    )

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._logger = get_logger(f"collector.{self.metadata.name}")

    @abstractmethod
    def collect(self) -> list[RawItem]:
        """Collect items from the source. Returns list of RawItem."""
        ...

    def health_check(self) -> CollectorHealth:
        """Default health check — subclasses can override for custom logic."""
        return CollectorHealth(
            collector_name=self.metadata.name,
            status="unknown",
            last_health_check=datetime.now(timezone.utc).isoformat(),
        )

    def get_metadata(self) -> CollectorMetadata:
        """Return this collector's metadata."""
        return self.metadata

    def get_required_credentials(self) -> list[str]:
        """Return list of required credential env var names."""
        return self.metadata.required_credentials

    def has_required_credentials(self) -> bool:
        """Check if all required credentials are present in environment."""
        import os
        return all(os.getenv(cred) for cred in self.metadata.required_credentials)


# ─── Registry ──────────────────────────────────────────────────────────


class CollectorRegistry:
    """Registry of all available collectors in the marketplace.

    Collectors auto-register on instantiation (via __init_subclass__ pattern)
    or can be manually registered via register().
    """

    _collectors: dict[str, MarketplaceCollector] = {}
    _collector_classes: dict[str, type[MarketplaceCollector]] = {}

    @classmethod
    def register(cls, collector: MarketplaceCollector) -> None:
        """Register a collector instance."""
        name = collector.metadata.name
        cls._collectors[name] = collector
        cls._collector_classes[name] = type(collector)
        get_logger("collector_registry").info(
            f"Registered collector: {name} ({collector.metadata.country}/{collector.metadata.category})"
        )

    @classmethod
    def register_class(cls, collector_class: type[MarketplaceCollector]) -> None:
        """Register a collector class (instantiates with default config)."""
        instance = collector_class()
        cls.register(instance)

    @classmethod
    def get(cls, name: str) -> MarketplaceCollector | None:
        """Get a collector by name."""
        return cls._collectors.get(name)

    @classmethod
    def list_all(cls) -> list[CollectorMetadata]:
        """List all registered collectors' metadata."""
        return [c.metadata for c in cls._collectors.values()]

    @classmethod
    def list_by_country(cls, country: str) -> list[CollectorMetadata]:
        """List collectors for a specific country (ISO code)."""
        return [c.metadata for c in cls._collectors.values() if c.metadata.country.upper() == country.upper()]

    @classmethod
    def list_by_category(cls, category: str) -> list[CollectorMetadata]:
        """List collectors in a specific category."""
        return [c.metadata for c in cls._collectors.values() if c.metadata.category == category]

    @classmethod
    def list_by_entity_type(cls, entity_type: str) -> list[CollectorMetadata]:
        """List collectors that produce a specific entity type."""
        return [c.metadata for c in cls._collectors.values() if entity_type in c.metadata.entity_types]

    @classmethod
    def get_stats(cls) -> dict:
        """Get aggregate stats about the registry."""
        from collections import Counter
        all_meta = cls.list_all()
        return {
            "total_collectors": len(all_meta),
            "by_country": dict(Counter(m.country for m in all_meta)),
            "by_category": dict(Counter(m.category for m in all_meta)),
            "by_health": dict(Counter(m.health_status for m in all_meta)),
            "requires_credentials": sum(1 for m in all_meta if m.required_credentials),
        }
