"""
Trust Layer — source reliability registry.

Every source (RSS feed, subreddit, HN, etc.) has a reliability score 0-1
that determines how much weight its evidence carries.

Default reliability by source type:
  hacker_news:      0.85
  github_issues:    0.80
  rss:              0.75
  google_news:      0.70
  reddit:           0.65
  product_hunt:     0.70
  g2:               0.80
  job_boards:       0.60

Specific high-credibility sources get bonuses:
  aps.dz:               0.90  (Algerian Press Service — official)
  tsa-algerie.com:      0.80
  elwatan.com:          0.80
  searchenginejournal:  0.90
  hubspot blog:         0.80
  Marketing Land:       0.75

Specific low-credibility patterns get penalties:
  affiliate:    0.20
  spam:         0.10
  unknown:      0.40

The Trust Layer is queried by the EvidenceValidator to weight evidence.
Sources with reliability < 0.30 are not counted toward minimum-sources
requirement (their evidence is recorded but doesn't help verify).

Reliability is also tunable via config (trust_layer.sources) and can
be adjusted by the Learning Engine based on observed outcomes.
"""
from __future__ import annotations
from core.logger import get_logger


# Default reliability by source type
_SOURCE_TYPE_RELIABILITY: dict[str, float] = {
    "hacker_news": 0.85,
    "github_issues": 0.80,
    "rss": 0.75,
    "google_news": 0.70,
    "reddit": 0.65,
    "product_hunt": 0.70,
    "g2": 0.80,
    "capterra": 0.75,
    "job_boards": 0.60,
    "ouedkniss": 0.65,         # Algerian classifieds
    "facebook_marketplace": 0.55,  # user-generated, varies
    "facebook_groups": 0.55,
    "test": 0.50,              # for testing
    "unknown": 0.40,
}


# High-credibility specific sources (by domain/substring match)
_HIGH_CREDIBILITY_SOURCES: dict[str, float] = {
    # Algerian press
    "aps.dz": 0.90,
    "aps.dz/algerie": 0.90,
    "aps algeria": 0.90,
    "aps_algeria": 0.90,
    "elwatan.com": 0.80,
    "elwatan": 0.80,
    "tsa-algerie.com": 0.80,
    "tsa algerie": 0.80,
    "tsa_algerie": 0.80,
    "liberte-algerie.com": 0.75,
    "liberte algerie": 0.75,
    "ennahar": 0.70,
    "echourouk": 0.70,
    # International tech/marketing press
    "searchenginejournal": 0.90,
    "searchengineland": 0.85,
    "marketingland": 0.75,
    "marketing land": 0.75,
    "hubspot blog": 0.80,
    "neil patel": 0.70,
    "content marketing institute": 0.80,
    "techcrunch": 0.85,
    "the verge": 0.85,
    # Hacker News + GitHub
    "hacker news": 0.85,
    "hacker_news": 0.85,
    "github": 0.80,
    # E-commerce platforms
    "remoteok": 0.65,
    "weworkremotely": 0.70,
    "workinstartups": 0.60,
}


# Low-credibility patterns (substring match → penalty)
_LOW_CREDIBILITY_PATTERNS: dict[str, float] = {
    "affiliate": 0.20,
    "spam": 0.10,
    "casino": 0.10,
    "porn": 0.05,
    "pharma": 0.10,
    "link building service": 0.15,
    "cheap essay": 0.10,
    "write my paper": 0.10,
}


class TrustLayer:
    """Source reliability registry.

    Provides get_reliability(source_id, source_type, source_name) → float 0-1.

    Reliability is computed as:
      1. Start with source_type default
      2. Override with specific source bonus if source_name matches
      3. Apply low-credibility penalty if any pattern matches

    The Learning Engine can later adjust these scores based on observed
    outcome accuracy (claims backed by source X that turned out to be
    true → boost X's reliability).
    """
    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._logger = get_logger("trust_layer")

        # Custom overrides from config
        self._custom_reliability: dict[str, float] = self._config.get("sources", {})

        # Learning-adjusted reliability (loaded from persistence)
        self._learned_reliability: dict[str, float] = {}

        # Minimum reliability to count toward min_sources requirement
        self._min_evidence_reliability: float = float(self._config.get("min_evidence_reliability", 0.30))

    def get_reliability(self, source_id: str, source_type: str = "unknown", source_name: str = "") -> float:
        """Get reliability score 0-1 for a source.

        Args:
            source_id: Unique source identifier (e.g. "aps.dz" or "reddit:r/algeria")
            source_type: Type of source (rss, reddit, hacker_news, etc.)
            source_name: Display name (used for substring matching)

        Returns:
            Reliability score 0-1
        """
        # 1. Check learned reliability first (highest priority)
        if source_id in self._learned_reliability:
            return self._learned_reliability[source_id]

        # 2. Check custom config overrides
        if source_id in self._custom_reliability:
            return self._custom_reliability[source_id]

        # 3. Start with source-type default
        reliability = _SOURCE_TYPE_RELIABILITY.get(source_type, 0.40)

        # 4. Override with specific source bonus
        source_name_lower = (source_name or "").lower()
        for pattern, bonus in _HIGH_CREDIBILITY_SOURCES.items():
            if pattern in source_name_lower or pattern in source_id.lower():
                reliability = max(reliability, bonus)
                break

        # 5. Apply low-credibility penalty
        for pattern, penalty in _LOW_CREDIBILITY_PATTERNS.items():
            if pattern in source_name_lower or pattern in source_id.lower():
                reliability = min(reliability, penalty)
                break

        return reliability

    def is_reliable_enough(self, reliability: float) -> bool:
        """Check if a source's reliability meets the minimum threshold
        to count toward the minimum-sources requirement.
        """
        return reliability >= self._min_evidence_reliability

    def update_learned_reliability(self, source_id: str, new_reliability: float) -> None:
        """Update a source's reliability based on Learning Engine feedback.

        Called when the Learning Engine observes that claims backed by
        a particular source turned out to be true or false.
        """
        new_reliability = max(0.0, min(1.0, new_reliability))
        self._learned_reliability[source_id] = new_reliability
        self._logger.info(f"Updated learned reliability for '{source_id}': {new_reliability:.2f}")

    def get_all_reliability(self) -> dict[str, float]:
        """Return all known reliability scores (for diagnostics)."""
        result = {}
        result.update(_SOURCE_TYPE_RELIABILITY)
        result.update(self._custom_reliability)
        result.update(self._learned_reliability)
        return result

    def get_stats(self) -> dict:
        """Return summary stats about the trust layer."""
        return {
            "total_sources_known": len(self.get_all_reliability()),
            "learned_sources_count": len(self._learned_reliability),
            "min_evidence_reliability": self._min_evidence_reliability,
            "high_credibility_sources": sum(1 for r in self.get_all_reliability().values() if r >= 0.75),
            "low_credibility_sources": sum(1 for r in self.get_all_reliability().values() if r < 0.40),
        }
