"""
Product Hunt collector — fetches recent product launches.

Uses Product Hunt's public RSS-like feed via their unofficial API
or the daily homepage scrape. No auth required for basic listings.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from core.models import RawItem
from collectors.base import BaseCollector


# Product Hunt has a GraphQL API but it requires auth.
# For free access, we use their RSS feed via a third-party converter
# or scrape the public API endpoints that don't require auth.
PH_API = "https://www.producthunt.com/frontend/graphql"
USER_AGENT = "Mozilla/5.0 (compatible; Market-Intel/1.0)"


class ProductHuntCollector(BaseCollector):
    name = "product_hunt"

    def __init__(self, config: dict, retry_config: dict | None = None):
        super().__init__(config, retry_config)
        self._categories: list[str] = config.get("categories", [
            "marketing", "seo", "analytics", "productivity", "developer-tools",
        ])

    def _fetch(self) -> list[RawItem]:
        all_items: list[RawItem] = []

        for category in self._categories:
            self._logger.info(f"Fetching Product Hunt: {category}", extra={"category": category})
            try:
                items = self._fetch_category(category)
                all_items.extend(items)
            except Exception as e:
                self._logger.warning(f"PH category failed: {category}", extra={"error": str(e)})

        return all_items

    def _fetch_category(self, category: str) -> list[RawItem]:
        """Fetch products from a category via Product Hunt's public API."""
        # Product Hunt exposes some data via their website's __NEXT_DATA__
        # We fetch the category page and extract the JSON
        url = f"https://www.producthunt.com/topics/{category}"

        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
        })

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception:
            # Fallback: try the API endpoint
            return self._fetch_api(category)

        # Extract __NEXT_DATA__ JSON
        import re
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
        if not match:
            return []

        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []

        # Navigate the data structure to find products
        props = data.get("props", {}).get("pageProps", {})
        products = props.get("posts", []) or props.get("products", [])

        items: list[RawItem] = []
        for product in products:
            name = product.get("name", "")
            tagline = product.get("tagline", "")
            url = product.get("website") or f"https://www.producthunt.com/posts/{product.get('slug', '')}"
            votes = product.get("votes_count", 0) or product.get("votes", 0)

            if not name:
                continue

            item = RawItem.create(
                source="product_hunt",
                source_name=f"Product Hunt / {category}",
                title=f"{name}: {tagline}",
                url=url,
                body=tagline,
                author=product.get("user", {}).get("name", ""),
                published_at=product.get("posted_at"),
                score=votes,
                tags=[category, "product_launch"],
                metadata={
                    "product_name": name,
                    "category": category,
                    "votes": votes,
                },
            )
            items.append(item)

        self._logger.info(f"PH/{category}: {len(items)} products", extra={"category": category, "items": len(items)})
        return items

    def _fetch_api(self, category: str) -> list[RawItem]:
        """Fallback: try fetching from Product Hunt's public API."""
        # This endpoint sometimes works without auth for basic data
        url = f"https://www.producthunt.com/api/v1/posts?search[topic]={category}"

        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return []

        posts = data.get("posts", [])
        items: list[RawItem] = []

        for post in posts:
            name = post.get("name", "")
            tagline = post.get("tagline", "")
            redirect_url = post.get("redirect_url", "")
            votes = post.get("votes_count", 0)

            if not name:
                continue

            item = RawItem.create(
                source="product_hunt",
                source_name=f"Product Hunt / {category}",
                title=f"{name}: {tagline}",
                url=redirect_url or f"https://www.producthunt.com/posts/{post.get('slug', '')}",
                body=tagline,
                score=votes,
                tags=[category, "product_launch"],
                metadata={"product_name": name, "category": category, "votes": votes},
            )
            items.append(item)

        return items
