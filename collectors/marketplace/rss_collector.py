"""
Marketplace RSS Collector — generic RSS collector using the marketplace interface.

Wraps the existing RSSCollector logic but exposes it via the standard
MarketplaceCollector interface so it's discoverable in the Collector Registry.
"""
from __future__ import annotations

from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from xml.etree import ElementTree as ET
from datetime import datetime, timezone
from core.models import RawItem
from collectors.marketplace.base import MarketplaceCollector, CollectorMetadata


class MarketplaceRSSCollector(MarketplaceCollector):
    """Generic RSS collector — marketplace interface.

    Config:
      feeds: list of {url, name}
      max_items_per_feed: int (default 50)
    """
    metadata = CollectorMetadata(
        name="rss",
        country="XX",  # multi-country — feeds define the country
        category="news",
        entity_types=["article", "news", "press_release"],
        description="Generic RSS/Atom feed collector — multi-country, multi-category",
        rate_limit_per_hour=120,
        reliability=0.75,
        cost_per_call=0.0,
        required_credentials=[],
        tags=["rss", "feed", "news", "generic"],
    )

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._feeds: list[dict] = self._config.get("feeds", [])
        self._max_items: int = int(self._config.get("max_items_per_feed", 50))
        self._retry_config: dict = self._config.get("retry", {"max_attempts": 3, "initial_backoff": 1.0})

    def collect(self) -> list[RawItem]:
        items: list[RawItem] = []
        for feed in self._feeds:
            url = feed.get("url", "")
            name = feed.get("name", url)
            if not url:
                continue
            try:
                feed_items = self._fetch_feed(url, name)
                items.extend(feed_items[: self._max_items])
            except Exception as e:
                self._logger.error(f"Failed to fetch feed '{name}' ({url}): {e}")
        return items

    def _fetch_feed(self, url: str, source_name: str) -> list[RawItem]:
        """Fetch and parse an RSS/Atom feed."""
        req = Request(url, headers={"User-Agent": "Market-Intel/1.0 (+https://github.com/marwangpt237/market-intel)"})
        with urlopen(req, timeout=30) as resp:
            data = resp.read()

        root = ET.fromstring(data)
        items: list[RawItem] = []

        # RSS 2.0
        for item_elem in root.findall(".//item"):
            title = self._get_text(item_elem, "title")
            link = self._get_text(item_elem, "link")
            description = self._get_text(item_elem, "description")
            pub_date = self._get_text(item_elem, "pubDate")
            author = self._get_text(item_elem, "author") or self._get_text(item_elem, "dc:creator")

            if title and link:
                items.append(RawItem.create(
                    source="rss",
                    source_name=source_name,
                    title=title,
                    url=link,
                    body=description,
                    author=author,
                    published_at=pub_date,
                ))

        # Atom
        for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            title = self._get_text(entry, "{http://www.w3.org/2005/Atom}title")
            link_elem = entry.find("{http://www.w3.org/2005/Atom}link")
            link = link_elem.get("href", "") if link_elem is not None else ""
            summary = self._get_text(entry, "{http://www.w3.org/2005/Atom}summary")
            content = self._get_text(entry, "{http://www.w3.org/2005/Atom}content")
            published = self._get_text(entry, "{http://www.w3.org/2005/Atom}published")
            author_elem = entry.find("{http://www.w3.org/2005/Atom}author")
            author = self._get_text(author_elem, "{http://www.w3.org/2005/Atom}name") if author_elem is not None else None

            if title and link:
                items.append(RawItem.create(
                    source="rss",
                    source_name=source_name,
                    title=title,
                    url=link,
                    body=summary or content,
                    author=author,
                    published_at=published,
                ))

        return items

    @staticmethod
    def _get_text(parent, tag: str) -> str | None:
        if parent is None:
            return None
        elem = parent.find(tag)
        if elem is None or elem.text is None:
            return None
        return elem.text.strip()
