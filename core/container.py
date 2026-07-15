"""
Dependency injection container.

Every component (collectors, processors, storage, reports) is instantiated
through this container. No component imports another directly — they receive
their dependencies via constructor.

Usage:
    container = Container(config)
    container.register_collector("reddit", RedditCollector(config))
    container.register_processor("dedup", DedupProcessor())
    items = container.run_collectors()
    items = container.run_processors(items)
    container.get_storage().save(items)
    container.get_report_generator().generate(items)
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable
from core.models import RawItem, ProcessedItem


@runtime_checkable
class Collector(Protocol):
    name: str
    def collect(self) -> list[RawItem]: ...


@runtime_checkable
class Processor(Protocol):
    name: str
    def process(self, items: list[ProcessedItem]) -> list[ProcessedItem]: ...


@runtime_checkable
class Storage(Protocol):
    def save(self, items: list[dict], run_id: str) -> str: ...
    def load_recent(self, days: int = 7) -> list[dict]: ...


@runtime_checkable
class ReportGenerator(Protocol):
    def generate(self, items: list[ProcessedItem], run_id: str) -> str: ...


class Container:
    """Dependency injection container — owns all component instances."""

    def __init__(self, config: dict):
        self._config = config
        self._collectors: dict[str, Collector] = {}
        self._processors: dict[str, Processor] = {}
        self._storage: Storage | None = None
        self._report_generator: ReportGenerator | None = None

    @property
    def config(self) -> dict:
        return self._config

    # ─── Registration ───────────────────────────────────────────────────

    def register_collector(self, name: str, collector: Collector) -> None:
        self._collectors[name] = collector

    def register_processor(self, name: str, processor: Processor) -> None:
        self._processors[name] = processor

    def set_storage(self, storage: Storage) -> None:
        self._storage = storage

    def set_report_generator(self, generator: ReportGenerator) -> None:
        self._report_generator = generator

    # ─── Access ─────────────────────────────────────────────────────────

    def get_collectors(self) -> dict[str, Collector]:
        return self._collectors

    def get_processors(self) -> dict[str, Processor]:
        return self._processors

    def get_storage(self) -> Storage:
        if self._storage is None:
            raise RuntimeError("Storage not configured")
        return self._storage

    def get_report_generator(self) -> ReportGenerator:
        if self._report_generator is None:
            raise RuntimeError("Report generator not configured")
        return self._report_generator
