"""
Similarity-based deduplication.

Replaces exact-match dedup with fuzzy title similarity using:
1. Jaccard similarity on token sets (fast, deterministic)
2. URL prefix matching (catches tracking parameters)

Two items are duplicates if:
- Title similarity > threshold (default 0.6), OR
- URLs share the same base path (ignoring query params)

Config:
  processors:
    similarity_dedup:
      enabled: true
      title_threshold: 0.6
      url_normalize: true
"""
from __future__ import annotations

import re
import urllib.parse
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


def tokenize(text: str) -> set[str]:
    """Lowercase, strip punctuation, split into tokens."""
    text = text.lower().strip()
    tokens = re.findall(r"\b[a-z0-9]{2,}\b", text)
    return set(tokens)


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def normalize_url(url: str) -> str:
    """Strip query params and fragments from URL for comparison."""
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


class SimilarityDedupProcessor(BaseProcessor):
    name = "similarity_dedup"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._title_threshold: float = (config or {}).get("title_threshold", 0.6)
        self._url_normalize: bool = (config or {}).get("url_normalize", True)

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        if not items:
            return items

        # Pre-compute token sets and normalized URLs
        tokens_list = [tokenize(item.title) for item in items]
        urls_list = [normalize_url(item.url) if self._url_normalize else item.url for item in items]

        # Track which items to keep
        keep = [True] * len(items)
        removed = 0

        for i in range(len(items)):
            if not keep[i]:
                continue
            for j in range(i + 1, len(items)):
                if not keep[j]:
                    continue

                # Check URL match first (fast)
                if urls_list[i] and urls_list[i] == urls_list[j]:
                    keep[j] = False
                    removed += 1
                    self._logger.debug(
                        f"URL duplicate: '{items[j].title[:50]}' matches '{items[i].title[:50]}'",
                        extra={"kept": items[i].url, "dropped": items[j].url}
                    )
                    continue

                # Check title similarity
                sim = jaccard_similarity(tokens_list[i], tokens_list[j])
                if sim >= self._title_threshold:
                    keep[j] = False
                    removed += 1
                    self._logger.debug(
                        f"Similar title (sim={sim:.2f}): '{items[j].title[:50]}' ~ '{items[i].title[:50]}'",
                        extra={"similarity": round(sim, 3), "kept": items[i].url, "dropped": items[j].url}
                    )

        result = [items[i] for i in range(len(items)) if keep[i]]
        self._logger.info(
            f"Similarity dedup: {len(items)} → {len(result)} (removed {removed})",
            extra={"input": len(items), "output": len(result), "removed": removed}
        )
        return result
