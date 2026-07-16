"""
Algerian Forum Collector — aggregates discussions from Algerian forums.

Sources (RSS when available):
  - djamelforum.com (general Algerian forum)
  - algerie-dz.com
  - forum.dzairmobile.com
  - mesdiscussions.net (Algeria section)

Forums are valuable for:
  - Complaints + pain points (unfiltered consumer sentiment)
  - Local product discussions
  - Service recommendations
  - Price comparisons (users post what they paid)
"""
from __future__ import annotations

from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from xml.etree import ElementTree as ET
from core.models import RawItem
from collectors.marketplace.base import MarketplaceCollector, CollectorMetadata


class AlgerianForumCollector(MarketplaceCollector):
    """Algerian forum aggregator.

    Config:
      sources: list of {url, name}
      max_items_per_source: int (default 30)
    """
    metadata = CollectorMetadata(
        name="algeria_forums",
        country="DZ",
        category="forum",
        entity_types=["discussion", "complaint", "recommendation", "question"],
        description="Algerian forum aggregator — djamelforum.com, algerie-dz.com, mesdiscussions.net",
        rate_limit_per_hour=40,
        reliability=0.60,                # user-generated, varies in quality
        cost_per_call=0.0,
        required_credentials=[],
        tags=["algeria", "forum", "discussion", "community", "dz"],
    )

    DEFAULT_SOURCES = [
        {"url": "https://www.djamelforum.com/feeds/forum/1", "name": "Djamelforum"},
        {"url": "https://www.algerie-dz.com/forums/feed.php", "name": "Algerie-DZ"},
        {"url": "https://forum.dzairmobile.com/external.php?type=RSS2", "name": "DzairMobile Forum"},
    ]

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._sources: list[dict] = self._config.get("sources", self.DEFAULT_SOURCES)
        self._max_items: int = int(self._config.get("max_items_per_source", 30))

    def collect(self) -> list[RawItem]:
        items: list[RawItem] = []
        for source in self._sources:
            url = source.get("url", "")
            name = source.get("name", url)
            if not url:
                continue
            try:
                source_items = self._fetch_rss(url, name)
                items.extend(source_items[: self._max_items])
            except Exception as e:
                self._logger.error(f"Failed to fetch forum '{name}' ({url}): {e}")

        self._logger.info(f"Algerian forums: collected {len(items)} items from {len(self._sources)} sources")
        return items

    def _fetch_rss(self, url: str, source_name: str) -> list[RawItem]:
        req = Request(url, headers={
            "User-Agent": "Market-Intel/1.0 (+https://github.com/marwangpt237/market-intel)",
            "Accept-Language": "fr-FR,fr;q=0.9",
        })
        try:
            with urlopen(req, timeout=20) as resp:
                data = resp.read()
        except (URLError, HTTPError) as e:
            self._logger.warning(f"Forum RSS error '{source_name}': {e}")
            return []

        try:
            root = ET.fromstring(data)
        except ET.ParseError as e:
            self._logger.warning(f"Forum RSS parse error '{source_name}': {e}")
            return []

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
                    source="algeria_forums",
                    source_name=source_name,
                    title=title,
                    url=link,
                    body=description,
                    author=author,
                    published_at=pub_date,
                    tags=["forum", "algeria", "discussion"],
                ))

        # Atom
        for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            title = self._get_text(entry, "{http://www.w3.org/2005/Atom}title")
            link_elem = entry.find("{http://www.w3.org/2005/Atom}link")
            link = link_elem.get("href", "") if link_elem is not None else ""
            summary = self._get_text(entry, "{http://www.w3.org/2005/Atom}summary")
            published = self._get_text(entry, "{http://www.w3.org/2005/Atom}published")
            author_elem = entry.find("{http://www.w3.org/2005/Atom}author")
            author = self._get_text(author_elem, "{http://www.w3.org/2005/Atom}name") if author_elem is not None else None

            if title and link:
                items.append(RawItem.create(
                    source="algeria_forums",
                    source_name=source_name,
                    title=title,
                    url=link,
                    body=summary,
                    author=author,
                    published_at=published,
                    tags=["forum", "algeria", "discussion"],
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
