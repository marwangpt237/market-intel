"""Algerian news collectors — major Algerian press outlets via RSS."""
from __future__ import annotations
from urllib.request import urlopen, Request
from xml.etree import ElementTree as ET
from core.models import RawItem
from collectors.marketplace.base import MarketplaceCollector, CollectorMetadata


class AlgerianNewsCollector(MarketplaceCollector):
    """Major Algerian news outlets — El Khabar, Echourouk, Ennahar, Liberte, El Watan.

    These are the highest-circulation Algerian newspapers. Their RSS feeds
    provide Arabic + French content covering politics, economy, society, sports.
    """
    metadata = CollectorMetadata(
        name="algeria_news",
        country="DZ",
        category="news",
        entity_types=["article", "news", "press_release"],
        description="Major Algerian newspapers — El Khabar, Echourouk, Ennahar, Liberte, El Watan",
        rate_limit_per_hour=60,
        reliability=0.80,
        cost_per_call=0.0,
        required_credentials=[],
        tags=["algeria", "news", "press", "arabic", "french", "dz"],
    )

    DEFAULT_SOURCES = [
        {"url": "https://www.elkhabar.com/feed/", "name": "El Khabar"},
        {"url": "https://www.echouroukonline.com/feed/", "name": "Echourouk"},
        {"url": "https://www.ennaharonline.com/feed/", "name": "Ennahar"},
        {"url": "https://www.liberte-algerie.com/rss", "name": "Liberte"},
        {"url": "https://www.elwatan.com/feed", "name": "El Watan"},
        {"url": "https://www.tsa-algerie.com/feed", "name": "TSA"},
        {"url": "https://www.aps.dz/algerie/feed", "name": "APS"},
    ]

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._sources: list[dict] = self._config.get("sources", self.DEFAULT_SOURCES)
        self._max_items: int = int(self._config.get("max_items_per_source", 20))

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
                self._logger.error(f"Failed to fetch news '{name}': {e}")
        self._logger.info(f"Algerian news: collected {len(items)} items from {len(self._sources)} sources")
        return items

    def _fetch_rss(self, url: str, source_name: str) -> list[RawItem]:
        req = Request(url, headers={
            "User-Agent": "Market-Intel/1.0",
            "Accept-Language": "fr-FR,fr;q=0.9,ar;q=0.8",
        })
        try:
            with urlopen(req, timeout=20) as resp:
                data = resp.read()
        except Exception as e:
            self._logger.warning(f"News RSS error '{source_name}': {e}")
            return []
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            return []
        items: list[RawItem] = []
        for item_elem in root.findall(".//item"):
            title = self._get_text(item_elem, "title")
            link = self._get_text(item_elem, "link")
            desc = self._get_text(item_elem, "description")
            pub = self._get_text(item_elem, "pubDate")
            if title and link:
                items.append(RawItem.create(
                    source="algeria_news", source_name=source_name,
                    title=title, url=link, body=desc, published_at=pub,
                    tags=["news", "algeria", "press"],
                ))
        # Atom
        for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            title = self._get_text(entry, "{http://www.w3.org/2005/Atom}title")
            link_elem = entry.find("{http://www.w3.org/2005/Atom}link")
            link = link_elem.get("href", "") if link_elem is not None else ""
            summary = self._get_text(entry, "{http://www.w3.org/2005/Atom}summary")
            published = self._get_text(entry, "{http://www.w3.org/2005/Atom}published")
            if title and link:
                items.append(RawItem.create(
                    source="algeria_news", source_name=source_name,
                    title=title, url=link, body=summary, published_at=published,
                    tags=["news", "algeria", "press"],
                ))
        return items

    @staticmethod
    def _get_text(parent, tag):
        if parent is None:
            return None
        elem = parent.find(tag)
        return elem.text.strip() if elem is not None and elem.text else None
