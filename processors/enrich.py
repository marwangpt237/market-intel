"""Enrichment processor — adds sentiment, keywords, and read time."""
from __future__ import annotations
import re
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


# Simple keyword stoplist
STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "can", "this", "that", "these",
    "those", "i", "you", "he", "she", "it", "we", "they", "what", "which",
    "who", "when", "where", "why", "how", "all", "each", "every", "some",
    "any", "no", "not", "as", "if", "than", "too", "very", "just", "about",
    "into", "through", "during", "before", "after", "above", "below",
    "up", "down", "out", "off", "over", "under", "again", "further",
    "then", "once", "here", "there", "your", "their", "its", "our",
})

POSITIVE_WORDS = frozenset({
    "growth", "increase", "success", "win", "best", "top", "leading",
    "innovative", "breakthrough", "opportunity", "boost", "improve",
    "rise", "gain", "profit", "revenue", "launch", "expand", "new",
    "upgrade", "optimize", "effective", "proven", "award", "achieve",
})

NEGATIVE_WORDS = frozenset({
    "decline", "decrease", "loss", "fail", "crash", "down", "drop",
    "fall", "cut", "shut", "close", "bankrupt", "lawsuit", "scandal",
    "breach", "hack", "attack", "threat", "risk", "warning", "alert",
    "concern", "problem", "issue", "crisis", "layoff", "fired",
})


class EnrichProcessor(BaseProcessor):
    name = "enrich"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._add_sentiment: bool = (config or {}).get("add_sentiment", True)
        self._add_keywords: bool = (config or {}).get("add_keywords", True)
        self._add_read_time: bool = (config or {}).get("add_read_time", True)

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        for item in items:
            if self._add_sentiment:
                item.sentiment = self._detect_sentiment(item.title + " " + item.body)
            if self._add_keywords:
                item.keywords = self._extract_keywords(item.title + " " + item.body)
            if self._add_read_time:
                item.read_time_minutes = max(1, len(item.body) // 200) if item.body else 1

        self._logger.info(f"Enriched {len(items)} items", extra={"items": len(items)})
        return items

    @staticmethod
    def _detect_sentiment(text: str) -> str:
        words = set(re.findall(r"\b[a-z]+\b", text.lower()))
        pos = len(words & POSITIVE_WORDS)
        neg = len(words & NEGATIVE_WORDS)
        if pos > neg:
            return "positive"
        if neg > pos:
            return "negative"
        return "neutral"

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        words = re.findall(r"\b[a-z]{3,}\b", text.lower())
        freq: dict[str, int] = {}
        for word in words:
            if word in STOP_WORDS:
                continue
            freq[word] = freq.get(word, 0) + 1
        # Sort by frequency, return top 5
        sorted_keywords = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [kw for kw, _ in sorted_keywords[:5]]
