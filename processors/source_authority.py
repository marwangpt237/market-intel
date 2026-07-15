"""
Source Authority Processor — Phase 5 data-quality module.

Adds `authority_score` (0-100) to each item based on:
  - Source type (HN > Reddit > RSS > unknown)
  - Specific source allowlist (established publications get bonus)
  - Item score (upvotes / engagement)
  - Language detection (non-English demoted)

Also flags items as `low_quality=True` when they fall below threshold,
so downstream processors (esp. FalsePositiveFilter) can drop them.

This runs BEFORE entity extraction / scoring — those processors can
weight items by authority_score to avoid spam / SEO slop / marketing
fluff polluting the entity graph.
"""
from __future__ import annotations

import re
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


# Source-type base authority (0-100)
_SOURCE_TYPE_AUTHORITY = {
    "hacker_news": 90,
    "github_issues": 85,
    "rss": 75,
    "google_news": 70,
    "reddit": 65,
    "product_hunt": 70,
    "g2": 80,
    "capterra": 75,
    "job_boards": 60,
}

# High-credibility specific sources (by source_name substring)
_HIGH_CREDIBILITY_SOURCES = {
    "search engine journal": 90,
    "hacker news": 90,
    "marketing land": 75,
    "hubspot blog": 80,
    "neil patel": 70,
    "content marketing institute": 80,
    "github": 85,
    "product hunt": 75,
    "g2": 80,
    "remoteok": 60,
    "workinstartups": 60,
}

# Low-credibility patterns (substring match)
_LOW_CREDIBILITY_PATTERNS = [
    "affiliate",
    "spam",
    "casino",
    "porn",
    "pharma",
    "link building service",
    "buy backlinks",
    "cheap essay",
    "write my paper",
]

# Non-English detection — simple heuristic: count non-ASCII chars + common non-EN articles
_NON_EN_INDICATORS = {
    # common Dutch
    "van", "het", "een", "en", "met", "voor", "dat", "zijn", "niet", "ook",
    "wat", "dit", "die", "wij", "ons", "hun", "maar", "ook", "naar", "bij",
    "hoe", "waarom", "wie", "wil", "kan", "moet", "heeft", "hebben",
    # common German
    "der", "die", "das", "und", "mit", "von", "nicht", "auch", "ist",
    "ein", "eine", "einer", "eines", "sich", "auf", "aus", "bei", "durch",
    # common French
    "le", "la", "les", "une", "avec", "pour", "que", "est", "pas",
    "dans", "nous", "vous", "ils", "elles", "mais", "ou", "etre",
    # common Spanish
    "los", "las", "una", "con", "para", "es", "no",
    "pero", "por", "su", "al", "del", "lo", "le", "se",
}


class SourceAuthorityProcessor(BaseProcessor):
    name = "source_authority"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._min_authority: int = self._config.get("min_authority", 25)
        self._demote_non_english: bool = self._config.get("demote_non_english", True)
        self._non_english_penalty: int = self._config.get("non_english_penalty", 40)

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        for item in items:
            authority = self._compute_authority(item)
            item.metadata["authority_score"] = authority
            item.metadata["low_quality"] = authority < self._min_authority

        kept = [i for i in items if not i.metadata.get("low_quality", False)]
        dropped = len(items) - len(kept)
        self._logger.info(
            f"Source authority: {len(kept)} items kept, {dropped} dropped (below {self._min_authority})",
            extra={"kept": len(kept), "dropped": dropped},
        )
        return kept

    def _compute_authority(self, item: ProcessedItem) -> int:
        """Compute authority score 0-100 for a single item."""
        score = 50  # baseline

        # 1. Source-type base
        source = item.source or ""
        source_type_base = _SOURCE_TYPE_AUTHORITY.get(source, 40)
        # Blend: 60% source-type base + 40% current score
        score = int(0.6 * source_type_base + 0.4 * score)

        # 2. Specific source bonus
        source_name = (item.source_name or "").lower()
        for pattern, bonus in _HIGH_CREDIBILITY_SOURCES.items():
            if pattern in source_name:
                score = max(score, bonus)
                break

        # 3. Item engagement score (upvotes / points)
        if item.score and item.score > 0:
            # Log scale: 10 pts = +5, 100 pts = +15, 1000 pts = +25
            import math
            engagement_bonus = min(25, int(5 * math.log10(max(1, item.score))))
            score += engagement_bonus

        # 4. Low-credibility penalty
        text = f"{item.title} {item.body or ''}".lower()
        for pattern in _LOW_CREDIBILITY_PATTERNS:
            if pattern in text:
                score -= 30
                break

        # 5. Non-English demotion
        if self._demote_non_english:
            if self._is_non_english(item.title, item.body or ""):
                score -= self._non_english_penalty

        return max(0, min(100, score))

    @staticmethod
    def _is_non_english(title: str, body: str) -> bool:
        """Quick non-English detection.

        Triggers if:
          - Title's first word is a common non-EN article
          - Body has > 5% non-ASCII chars (Latin-1 supplement)
          - Multiple non-EN indicator words appear in the text
          - Language-specific patterns (Dutch "ij", German "ß", etc.)
        """
        if not body and not title:
            return False

        title_lower = (title or "").lower().strip()
        body_lower = (body or "").lower()

        # 1. Check title's first word against non-EN indicators
        if title_lower:
            words = title_lower.split()
            if words and words[0] in _NON_EN_INDICATORS:
                return True

        # 2. Count non-EN indicator words across full text
        full_text = f"{title_lower} {body_lower}"
        word_set = set(re.findall(r"\b\w+\b", full_text))
        non_en_word_count = len(word_set & _NON_EN_INDICATORS)
        # If 3+ non-EN indicator words appear, it's almost certainly not English
        if non_en_word_count >= 3:
            return True

        # 3. Non-ASCII char ratio (accented chars)
        if len(body) > 50:
            non_ascii = sum(1 for c in body if ord(c) > 127)
            if non_ascii / len(body) > 0.05:
                return True

        # 4. Dutch-specific digraphs + indicator words
        if "ij" in title_lower and any(w in title_lower for w in ["van", "het", "een", "met", "wat", "dit"]):
            return True

        # 5. German-specific chars + indicator words
        if any(c in body_lower for c in ["ß", "ä", "ö", "ü"]):
            if any(w in body_lower for w in ["und", "nicht", "mit", "von", "der", "die", "das"]):
                return True

        return False
