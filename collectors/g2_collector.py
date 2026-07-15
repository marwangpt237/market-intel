"""
G2 collector — fetches software reviews from G2.com.

G2 doesn't have a public API, so we scrape their public review pages.
Focuses on marketing/SEO/analytics software categories.
"""
from __future__ import annotations

import re
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from core.models import RawItem
from collectors.base import BaseCollector


G2_BASE = "https://www.g2.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"


class G2Collector(BaseCollector):
    name = "g2"

    def __init__(self, config: dict, retry_config: dict | None = None):
        super().__init__(config, retry_config)
        self._categories: list[str] = config.get("categories", [
            "marketing-automation", "seo-tools", "email-marketing",
            "social-media-marketing", "analytics",
        ])

    def _fetch(self) -> list[RawItem]:
        all_items: list[RawItem] = []

        for category in self._categories:
            self._logger.info(f"Fetching G2: {category}", extra={"category": category})
            try:
                items = self._fetch_category(category)
                all_items.extend(items)
            except Exception as e:
                self._logger.warning(f"G2 category failed: {category}", extra={"error": str(e)})

        return all_items

    def _fetch_category(self, category: str) -> list[RawItem]:
        """Scrape G2 category page for product listings + recent reviews."""
        url = f"{G2_BASE}/categories/{category}"
        params = "?sort=recent_reviews"

        req = urllib.request.Request(url + params, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
            "Accept-Language": "en-US,en;q=0.9",
        })

        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        items: list[RawItem] = []

        # Extract product cards from G2's HTML
        # G2 uses data attributes and specific class patterns
        product_pattern = re.compile(
            r'<div[^>]*class="[^"]*product-listing[^"]*"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="[^"]*product-listing|</section|$)',
            re.DOTALL,
        )

        # Fallback: look for product links with review counts
        product_links = re.findall(
            r'href="(/products/[^"]+)"[^>]*>.*?class="[^"]*product-name[^"]*"[^>]*>([^<]+)</a>',
            html, re.DOTALL | re.IGNORECASE,
        )

        # Another approach: JSON-LD data
        jsonld_pattern = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)
        for match in jsonld_pattern.finditer(html):
            try:
                import json
                data = json.loads(match.group(1))
                if isinstance(data, dict) and data.get("@type") == "Product":
                    name = data.get("name", "")
                    url = f"{G2_BASE}/products/{data.get('slug', '')}"
                    reviews = data.get("aggregateRating", {})
                    rating = reviews.get("ratingValue", 0)
                    review_count = reviews.get("reviewCount", 0)

                    if name:
                        item = RawItem.create(
                            source="g2",
                            source_name=f"G2 / {category}",
                            title=f"{name} — {review_count} reviews ({rating}★)",
                            url=url,
                            body=data.get("description", "")[:500],
                            score=review_count,
                            tags=[category, "review"],
                            metadata={
                                "product_name": name,
                                "category": category,
                                "rating": rating,
                                "review_count": review_count,
                            },
                        )
                        items.append(item)
            except Exception:
                continue

        # If JSON-LD didn't work, try the product links
        if not items and product_links:
            for path, name in product_links[:15]:
                name = name.strip()
                if not name:
                    continue
                item = RawItem.create(
                    source="g2",
                    source_name=f"G2 / {category}",
                    title=name,
                    url=f"{G2_BASE}{path}",
                    body="",
                    tags=[category, "review"],
                    metadata={"category": category, "product_name": name},
                )
                items.append(item)

        self._logger.info(f"G2/{category}: {len(items)} products", extra={"category": category, "items": len(items)})
        return items
