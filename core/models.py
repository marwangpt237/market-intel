"""
Common data models for Market-Intel.

All collectors produce RawItem objects. Processors transform them into
ProcessedItem objects. Storage persists both. Reports aggregate them.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
import hashlib
import json


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_id(source: str, url: str) -> str:
    """Generate a deterministic ID from source + URL."""
    raw = f"{source}:{url}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class RawItem:
    """The common schema every collector must produce."""
    id: str
    source: str                     # e.g., "reddit", "rss", "google_news"
    source_name: str                # e.g., "r/marketing", "Search Engine Journal"
    title: str
    url: str
    body: str = ""                  # excerpt, description, or selftext
    author: str = ""
    published_at: Optional[str] = None  # ISO 8601
    collected_at: str = field(default_factory=lambda: utc_now().isoformat())
    score: Optional[int] = None     # upvotes, engagement metric, or None
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(cls, source: str, source_name: str, title: str, url: str, **kwargs) -> "RawItem":
        item_id = generate_id(source, url)
        return cls(id=item_id, source=source, source_name=source_name, title=title, url=url, **kwargs)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProcessedItem:
    """A RawItem after processing (dedup, enrichment, etc.)."""
    id: str
    source: str
    source_name: str
    title: str
    url: str
    body: str = ""
    author: str = ""
    published_at: Optional[str] = None
    collected_at: str = ""
    score: Optional[int] = None
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    # Enriched fields
    sentiment: str = "neutral"      # positive | negative | neutral
    keywords: list[str] = field(default_factory=list)
    read_time_minutes: int = 0
    dedup_key: str = ""
    processed_at: str = field(default_factory=lambda: utc_now().isoformat())

    @classmethod
    def from_raw(cls, raw: RawItem) -> "ProcessedItem":
        return cls(
            id=raw.id,
            source=raw.source,
            source_name=raw.source_name,
            title=raw.title,
            url=raw.url,
            body=raw.body,
            author=raw.author,
            published_at=raw.published_at,
            collected_at=raw.collected_at,
            score=raw.score,
            tags=raw.tags,
            metadata=raw.metadata,
            dedup_key=hashlib.sha256(f"{raw.title.lower().strip()}".encode()).hexdigest()[:16],
        )

    def to_dict(self) -> dict:
        return asdict(self)


def serialize_items(items: list[dict]) -> str:
    """Serialize a list of item dicts to a pretty-printed JSON string."""
    return json.dumps(items, indent=2, default=str, ensure_ascii=False)
