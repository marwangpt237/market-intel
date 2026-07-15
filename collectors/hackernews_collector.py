"""
Hacker News collector — fetches top stories from Hacker News.

Uses the official HN Algolia search API (free, no auth).
Searches for marketing/startup/product-related keywords.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from core.models import RawItem
from collectors.base import BaseCollector


HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
USER_AGENT = "Market-Intel/1.0"


class HackerNewsCollector(BaseCollector):
    name = "hacker_news"

    def __init__(self, config: dict, retry_config: dict | None = None):
        super().__init__(config, retry_config)
        self._queries: list[str] = config.get("queries", [
            "marketing tools", "startup marketing", "growth hacking",
            "SEO tools", "SaaS marketing", "product launch",
        ])
        self._min_points: int = config.get("min_points", 5)
        self._tags: str = config.get("tags", "story")  # story | comment | (story,comment)

    def _fetch(self) -> list[RawItem]:
        all_items: list[RawItem] = []

        for query in self._queries:
            self._logger.info(f"Searching HN: {query}", extra={"query": query})
            try:
                items = self._fetch_query(query)
                all_items.extend(items)
            except Exception as e:
                self._logger.warning(f"HN query failed: {query}", extra={"error": str(e)})

        return all_items

    def _fetch_query(self, query: str) -> list[RawItem]:
        params = {
            "query": query,
            "tags": self._tags,
            "numericFilters": f"points>={self._min_points}",
            "hitsPerPage": 25,
        }
        url = f"{HN_SEARCH_URL}?{urllib.parse.urlencode(params)}"

        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        hits = data.get("hits", [])
        items: list[RawItem] = []

        for hit in hits:
            title = hit.get("title") or hit.get("story_title") or ""
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            points = hit.get("points", 0) or 0
            author = hit.get("author", "")
            created_at = hit.get("created_at") or hit.get("created_at_i")

            if not title:
                continue

            # Convert timestamp if needed
            if isinstance(created_at, int):
                created_at = datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat()

            body = (hit.get("story_text") or hit.get("comment_text") or "")[:500]

            item = RawItem.create(
                source="hacker_news",
                source_name="Hacker News",
                title=title.strip(),
                url=url,
                body=body,
                author=author,
                published_at=created_at,
                score=points,
                tags=[query],
                metadata={
                    "hn_id": hit.get("objectID"),
                    "num_comments": hit.get("num_comments", 0),
                    "query": query,
                },
            )
            items.append(item)

        self._logger.info(f"HN '{query}': {len(items)} items", extra={"query": query, "items": len(items)})
        return items
