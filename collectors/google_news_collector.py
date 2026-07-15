"""
Google News collector — fetches news articles via Google News RSS feeds.

Google News provides RSS feeds for search queries that can be filtered
by language and country. No API key required.
"""
from __future__ import annotations

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from core.models import RawItem
from core.logger import get_logger
from collectors.base import BaseCollector
from collectors.rss_collector import RSSCollector


GOOGLE_NEWS_BASE = "https://news.google.com/rss/search"
USER_AGENT = "Market-Intel/1.0 (Python; +https://github.com/marwangpt237/market-intel)"


class GoogleNewsCollector(BaseCollector):
    name = "google_news"

    def __init__(self, config: dict, retry_config: dict | None = None):
        super().__init__(config, retry_config)
        self._queries: list[str] = config.get("queries", [])
        self._language: str = config.get("language", "en")
        self._country: str = config.get("country", "US")

    def _fetch(self) -> list[RawItem]:
        all_items: list[RawItem] = []

        for query in self._queries:
            self._logger.info(f"Searching Google News: {query}", extra={"query": query})
            try:
                items = self._fetch_query(query)
                all_items.extend(items)
            except Exception as e:
                self._logger.warning(
                    f"Failed to fetch Google News query: {query}",
                    extra={"query": query, "error": str(e)}
                )

        return all_items

    def _fetch_query(self, query: str) -> list[RawItem]:
        """Fetch news for a single search query."""
        # Build the Google News RSS URL
        params = {
            "q": query,
            "hl": f"{self._language}-{self._country}",
            "gl": self._country,
            "ceid": f"{self._country}:{self._language}",
        }
        url = f"{GOOGLE_NEWS_BASE}?{urllib.parse.urlencode(params)}"

        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/xml, text/xml",
        })

        with urllib.request.urlopen(req, timeout=20) as resp:
            xml_content = resp.read().decode("utf-8", errors="replace")

        root = ET.fromstring(xml_content)
        items: list[RawItem] = []

        channel = root.find("channel")
        if channel is None:
            return items

        for item_elem in channel.findall("item"):
            title = RSSCollector._get_text(item_elem, "title")
            link = RSSCollector._get_text(item_elem, "link")
            description = RSSCollector._get_text(item_elem, "description")
            pub_date = RSSCollector._get_text(item_elem, "pubDate")
            source = RSSCollector._get_text(item_elem, "source")

            if not title or not link:
                continue

            # Google News titles often end with " - Source Name"
            # Extract the source name if present
            source_name = "Google News"
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title = parts[0].strip()
                source_name = parts[1].strip()

            body = RSSCollector._strip_html(description)[:500] if description else ""

            item = RawItem.create(
                source="google_news",
                source_name=source_name,
                title=title,
                url=link,
                body=body,
                author=source or source_name,
                published_at=RSSCollector._parse_date(pub_date),
                tags=[query],
                metadata={
                    "query": query,
                    "original_source": source or "",
                },
            )
            items.append(item)

        self._logger.info(
            f"Query '{query}': {len(items)} items",
            extra={"query": query, "items": len(items)}
        )
        return items
