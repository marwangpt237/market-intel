"""
Trend detection — identifies topics gaining momentum.

Compares current run's items against historical data (from storage).
Detects:
1. Volume spikes — topics with significantly more mentions than usual
2. Emerging topics — new keywords not seen in previous runs
3. Declining topics — keywords losing traction

Output: item.metadata["trend"] = "rising" | "hot" | "declining" | "stable"
Plus a trends summary stored in workflow summary.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


class TrendDetectionProcessor(BaseProcessor):
    name = "trend_detection"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._spike_threshold: float = (config or {}).get("spike_threshold", 2.0)  # 2x normal volume
        self._hot_threshold: float = (config or {}).get("hot_threshold", 3.0)  # 3x = "hot"
        self._history: dict[str, int] = {}  # keyword → average count

    def set_history(self, historical_keywords: dict[str, int]) -> None:
        """Set historical keyword counts for comparison.
        Called by the workflow before processing.
        """
        self._history = historical_keywords

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        # Count current keyword frequency
        current_counts: Counter = Counter()
        for item in items:
            for kw in item.keywords:
                current_counts[kw] += 1

        # Compare against history
        trends: dict[str, str] = {}
        emerging: list[str] = []

        for keyword, count in current_counts.items():
            historical_avg = self._history.get(keyword, 0)

            if historical_avg == 0:
                # Never seen before
                if count >= 3:
                    trends[keyword] = "emerging"
                    emerging.append(keyword)
                continue

            ratio = count / historical_avg

            if ratio >= self._hot_threshold:
                trends[keyword] = "hot"
            elif ratio >= self._spike_threshold:
                trends[keyword] = "rising"
            elif ratio < 0.5:
                trends[keyword] = "declining"
            else:
                trends[keyword] = "stable"

        # Assign trend labels to items
        for item in items:
            item_trends = [trends.get(kw, "stable") for kw in item.keywords]
            if "hot" in item_trends:
                item.metadata["trend"] = "hot"
            elif "rising" in item_trends:
                item.metadata["trend"] = "rising"
            elif "emerging" in item_trends:
                item.metadata["trend"] = "emerging"
            elif "declining" in item_trends:
                item.metadata["trend"] = "declining"
            else:
                item.metadata["trend"] = "stable"

        # Store trend summary
        hot_topics = [kw for kw, trend in trends.items() if trend == "hot"]
        rising_topics = [kw for kw, trend in trends.items() if trend == "rising"]
        declining_topics = [kw for kw, trend in trends.items() if trend == "declining"]

        self._logger.info(
            f"Trends: {len(hot_topics)} hot, {len(rising_topics)} rising, "
            f"{len(declining_topics)} declining, {len(emerging)} emerging",
            extra={
                "hot": hot_topics[:5],
                "rising": rising_topics[:5],
                "declining": declining_topics[:5],
                "emerging": emerging[:5],
            }
        )

        # Store on first item for the report generator to pick up
        if items:
            items[0].metadata["_trend_summary"] = {
                "hot": hot_topics[:10],
                "rising": rising_topics[:10],
                "declining": declining_topics[:10],
                "emerging": emerging[:10],
            }

        return items
