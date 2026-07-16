"""
Algerian Job Board Collector — aggregates job postings from Algerian job sites.

Sources (RSS when available, HTML scrape otherwise):
  - nerdal.com (Algerian tech jobs)
  - algeriejobs.com
  - emploi.nouvelobs.com (Algeria filter)
  - jobalgerie.com
  - Recrutement-dz.com

The collector tags each item with the source + job category for downstream
processing by the Algeria Pack + Client Acquisition modules.
"""
from __future__ import annotations

from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from xml.etree import ElementTree as ET
from core.models import RawItem
from collectors.marketplace.base import MarketplaceCollector, CollectorMetadata


class AlgerianJobBoardCollector(MarketplaceCollector):
    """Algerian job boards aggregator.

    Config:
      sources: list of {url, name, type: "rss"|"html"}
      max_items_per_source: int (default 30)
    """
    metadata = CollectorMetadata(
        name="algeria_jobs",
        country="DZ",
        category="jobs",
        entity_types=["job", "company", "skill"],
        description="Algerian job boards aggregator — nerdal.com, algeriejobs.com, Recrutement-dz, etc.",
        rate_limit_per_hour=60,
        reliability=0.70,
        cost_per_call=0.0,
        required_credentials=[],
        tags=["algeria", "jobs", "employment", "recruitment", "dz"],
    )

    # Default Algerian job board RSS feeds
    DEFAULT_SOURCES = [
        {"url": "https://www.nouvelobs.com/emploi/rss.xml", "name": "NouvelObs Emploi", "type": "rss"},
        {"url": "https://www.algeriejobs.com/jobs/rss", "name": "AlgerieJobs", "type": "rss"},
        {"url": "https://www.recrutement-dz.com/feed", "name": "Recrutement-DZ", "type": "rss"},
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
            source_type = source.get("type", "rss")

            if not url:
                continue

            try:
                if source_type == "rss":
                    source_items = self._fetch_rss(url, name)
                else:
                    source_items = self._fetch_html(url, name)
                items.extend(source_items[: self._max_items])
            except Exception as e:
                self._logger.error(f"Failed to fetch job board '{name}' ({url}): {e}")

        self._logger.info(f"Algerian job boards: collected {len(items)} items from {len(self._sources)} sources")
        return items

    def _fetch_rss(self, url: str, source_name: str) -> list[RawItem]:
        """Fetch and parse an RSS feed."""
        req = Request(url, headers={
            "User-Agent": "Market-Intel/1.0 (+https://github.com/marwangpt237/market-intel)",
            "Accept-Language": "fr-FR,fr;q=0.9",
        })
        try:
            with urlopen(req, timeout=20) as resp:
                data = resp.read()
        except (URLError, HTTPError) as e:
            self._logger.warning(f"Job board RSS error '{source_name}': {e}")
            return []

        try:
            root = ET.fromstring(data)
        except ET.ParseError as e:
            self._logger.warning(f"Job board RSS parse error '{source_name}': {e}")
            return []

        items: list[RawItem] = []

        # RSS 2.0
        for item_elem in root.findall(".//item"):
            title = self._get_text(item_elem, "title")
            link = self._get_text(item_elem, "link")
            description = self._get_text(item_elem, "description")
            pub_date = self._get_text(item_elem, "pubDate")

            if title and link:
                items.append(RawItem.create(
                    source="algeria_jobs",
                    source_name=source_name,
                    title=title,
                    url=link,
                    body=description,
                    author=None,
                    published_at=pub_date,
                    tags=["job", "algeria", "employment"],
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
                    source="algeria_jobs",
                    source_name=source_name,
                    title=title,
                    url=link,
                    body=summary,
                    author=None,
                    published_at=published,
                    tags=["job", "algeria", "employment"],
                ))

        return items

    def _fetch_html(self, url: str, source_name: str) -> list[RawItem]:
        """Fetch and parse an HTML job listing page (basic)."""
        # HTML scraping is best-effort — for production, use proper scraping libs
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept-Language": "fr-FR,fr;q=0.9",
        })
        try:
            with urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except (URLError, HTTPError) as e:
            self._logger.warning(f"Job board HTML error '{source_name}': {e}")
            return []

        # Simple regex extraction of job titles + links (best-effort)
        items: list[RawItem] = []
        import re
        # Common patterns: <a href="/job/..." class="job-title">Title</a>
        title_patterns = [
            r'<a[^>]*href="(/job/[^"]+)"[^>]*>([^<]+)</a>',
            r'<h[23][^>]*><a[^>]*href="([^"]+)"[^>]*>([^<]+)</a></h[23]>',
            r'<a[^>]*class="[^"]*title[^"]*"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
        ]

        for pattern in title_patterns:
            for match in re.finditer(pattern, html, re.IGNORECASE):
                link = match.group(1)
                title = match.group(2).strip()
                if not link.startswith("http"):
                    base = url.split("/")[0] + "//" + url.split("/")[2]
                    link = base + link

                items.append(RawItem.create(
                    source="algeria_jobs",
                    source_name=source_name,
                    title=title,
                    url=link,
                    body="",
                    tags=["job", "algeria", "employment"],
                ))
                if len(items) >= self._max_items:
                    return items

        return items

    @staticmethod
    def _get_text(parent, tag: str) -> str | None:
        if parent is None:
            return None
        elem = parent.find(tag)
        if elem is None or elem.text is None:
            return None
        return elem.text.strip()
