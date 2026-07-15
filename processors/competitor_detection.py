"""
Competitor detection — identifies when competitors are mentioned.

Uses entity extraction results + competitor dictionary to find:
1. Direct competitor mentions (by name)
2. Comparison signals ("X vs Y", "alternative to X", "better than X")
3. Switching signals ("moving from X to Y", "replacing X")

Output: item.metadata["competitor_mentions"] = list of {competitor, signal_type, context}
"""
from __future__ import annotations

import re
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


# Default competitor keywords (extend via config)
DEFAULT_COMPETITORS = {
    "maltego": {"category": "OSINT", "alternatives": ["argus", "spiderfoot", "inteltechniques"]},
    "hubspot": {"category": "Marketing", "alternatives": ["salesforce", "marketo", "pardot"]},
    "semrush": {"category": "SEO", "alternatives": ["ahrefs", "moz", "spyfu"]},
    "ahrefs": {"category": "SEO", "alternatives": ["semrush", "moz", "spyfu"]},
    "google analytics": {"category": "Analytics", "alternatives": ["amplitude", "mixpanel", "plausible"]},
    "mailchimp": {"category": "Email", "alternatives": ["convertkit", "brevo", "mailerlite"]},
    "salesforce": {"category": "CRM", "alternatives": ["hubspot", "pipedrive", "zoho"]},
    "shodan": {"category": "Security", "alternatives": ["censys", "zoomEye"]},
    "shopify": {"category": "Ecommerce", "alternatives": ["woocommerce", "bigcommerce", "magento"]},
    "wordpress": {"category": "CMS", "alternatives": ["webflow", "squarespace", "ghost"]},
}

# Pattern-based signal detection
COMPARISON_PATTERNS = [
    re.compile(r"\b(?:vs|versus|or)\s+([a-z]+)", re.I),
    re.compile(r"\balternative\s+to\s+([a-z][a-z\s]+?)(?:\.|,|$)", re.I),
    re.compile(r"\bbetter\s+than\s+([a-z][a-z\s]+?)(?:\.|,|$)", re.I),
    re.compile(r"\bcheaper\s+than\s+([a-z][a-z\s]+?)(?:\.|,|$)", re.I),
    re.compile(r"\bmoving\s+from\s+([a-z]+)\s+to\s+([a-z]+)", re.I),
    re.compile(r"\breplacing\s+([a-z]+)", re.I),
    re.compile(r"\bswitching\s+from\s+([a-z]+)", re.I),
    re.compile(r"\b([a-z]+)\s+pricing", re.I),
    re.compile(r"\b([a-z]+)\s+is\s+(?:too\s+)?(?:expensive|pricey|costly)", re.I),
]


class CompetitorDetectionProcessor(BaseProcessor):
    name = "competitor_detection"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._competitors: dict[str, dict] = dict(DEFAULT_COMPETITORS)
        # Merge any custom competitors from config
        for comp in (config or {}).get("competitors", []):
            self._competitors[comp.lower()] = {"category": "custom", "alternatives": []}

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        total_mentions = 0

        for item in items:
            text = f"{item.title} {item.body}".lower()
            mentions: list[dict] = []

            # 1. Direct competitor name mentions
            for competitor, info in self._competitors.items():
                if competitor in text:
                    signal_type = "mention"
                    # Check if it's a pricing complaint
                    if "pricing" in text or "expensive" in text or "costly" in text:
                        signal_type = "pricing_complaint"
                    # Check if alternatives are sought
                    if "alternative" in text or "instead" in text or "switching" in text:
                        signal_type = "seeking_alternative"

                    mentions.append({
                        "competitor": competitor,
                        "category": info.get("category", "unknown"),
                        "signal": signal_type,
                        "context": text[:200],
                    })

            # 2. Pattern-based detection
            for pattern in COMPARISON_PATTERNS:
                for match in pattern.finditer(text):
                    matched_text = match.group(0).strip()
                    # Check if any matched group is a known competitor
                    for group in match.groups():
                        if group and group.strip().lower() in self._competitors:
                            mentions.append({
                                "competitor": group.strip().lower(),
                                "category": self._competitors[group.strip().lower()].get("category", "unknown"),
                                "signal": "comparison",
                                "context": matched_text,
                            })

            # Deduplicate by competitor
            seen_comps: set[str] = set()
            unique_mentions = []
            for m in mentions:
                if m["competitor"] not in seen_comps:
                    seen_comps.add(m["competitor"])
                    unique_mentions.append(m)

            if unique_mentions:
                item.metadata["competitor_mentions"] = unique_mentions
                total_mentions += len(unique_mentions)

        self._logger.info(
            f"Competitor detection: {total_mentions} mentions across {len(items)} items",
            extra={"total_mentions": total_mentions, "items": len(items)}
        )
        return items
