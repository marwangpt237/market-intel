"""Algerian tenders collector — public procurement notices."""
from __future__ import annotations
from urllib.request import urlopen, Request
from xml.etree import ElementTree as ET
from core.models import RawItem
from collectors.marketplace.base import MarketplaceCollector, CollectorMetadata


class AlgerianTendersCollector(MarketplaceCollector):
    """Algerian public procurement + tenders.

    Sources:
      - BOMOP (Bulletin Officiel des Marchés Publics)
      - ANEP (Agence Nationale des Editions et Publicités)
      - Ministry portals

    Tenders indicate: government spending, infrastructure projects, sector growth.
    """
    metadata = CollectorMetadata(
        name="algeria_tenders",
        country="DZ",
        category="government",
        entity_types=["tender", "contract", "procurement"],
        description="Algerian public procurement + tenders — BOMOP, ANEP, ministry portals",
        rate_limit_per_hour=20,
        reliability=0.90,  # official government data
        cost_per_call=0.0,
        required_credentials=[],
        tags=["algeria", "government", "tenders", "procurement", "bomop", "dz"],
    )

    DEFAULT_SOURCES = [
        {"url": "https://www.bomop.dz/feed", "name": "BOMOP"},
        {"url": "https://www.anep.dz/feed", "name": "ANEP"},
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
                self._logger.error(f"Tenders '{name}' failed: {e}")
        self._logger.info(f"Algerian tenders: collected {len(items)} notices")
        return items

    def _fetch_rss(self, url: str, source_name: str) -> list[RawItem]:
        req = Request(url, headers={"User-Agent": "Market-Intel/1.0", "Accept-Language": "fr-FR,fr;q=0.9"})
        try:
            with urlopen(req, timeout=20) as resp:
                data = resp.read()
        except Exception:
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
                    source="algeria_tenders", source_name=source_name,
                    title=title, url=link, body=desc, published_at=pub,
                    tags=["tender", "government", "procurement", "algeria"],
                ))
        return items

    @staticmethod
    def _get_text(parent, tag):
        if parent is None:
            return None
        elem = parent.find(tag)
        return elem.text.strip() if elem is not None and elem.text else None
