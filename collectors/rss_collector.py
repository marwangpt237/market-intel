"""
RSS collector — fetches and parses RSS/Atom feeds.

Uses xml.etree.ElementTree (stdlib) for parsing — no feedparser dependency.
Supports both RSS 2.0 and Atom 1.0 formats.
"""
from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from core.models import RawItem
from core.logger import get_logger
from collectors.base import BaseCollector


USER_AGENT = "Market-Intel/1.0 (Python; +https://github.com/marwangpt237/market-intel)"


class RSSCollector(BaseCollector):
    name = "rss"

    def __init__(self, config: dict, retry_config: dict | None = None):
        super().__init__(config, retry_config)
        self._feeds: list[dict] = config.get("feeds", [])

    def _fetch(self) -> list[RawItem]:
        all_items: list[RawItem] = []

        for feed_config in self._feeds:
            url = feed_config.get("url", "")
            name = feed_config.get("name", url)
            if not url:
                continue

            self._logger.info(f"Fetching feed: {name}", extra={"feed": name})
            try:
                items = self._fetch_feed(url, name)
                all_items.extend(items)
            except Exception as e:
                self._logger.warning(
                    f"Failed to fetch feed: {name}",
                    extra={"feed": name, "error": str(e)}
                )

        return all_items

    def _fetch_feed(self, url: str, name: str) -> list[RawItem]:
        """Fetch and parse a single RSS/Atom feed."""
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/xml, text/xml, application/rss+xml, application/atom+xml",
        })

        with urllib.request.urlopen(req, timeout=20) as resp:
            xml_content = resp.read().decode("utf-8", errors="replace")

        root = ET.fromstring(xml_content)

        # Detect feed type: RSS 2.0 vs Atom 1.0
        if root.tag == "rss":
            return self._parse_rss(root, url, name)
        elif root.tag.endswith("feed"):  # Atom
            return self._parse_atom(root, url, name)
        else:
            self._logger.warning(f"Unknown feed format: {name}", extra={"feed": name, "root_tag": root.tag})
            return []

    def _parse_rss(self, root: ET.Element, feed_url: str, feed_name: str) -> list[RawItem]:
        """Parse RSS 2.0 format."""
        items: list[RawItem] = []
        channel = root.find("channel")
        if channel is None:
            return items

        for item_elem in channel.findall("item"):
            title = self._get_text(item_elem, "title")
            link = self._get_text(item_elem, "link")
            description = self._get_text(item_elem, "description")
            pub_date = self._get_text(item_elem, "pubDate")
            author = self._get_text(item_elem, "author") or self._get_text(item_elem, "{http://purl.org/dc/elements/1.1/}creator")

            if not title or not link:
                continue

            # Clean description (strip HTML tags)
            body = self._strip_html(description)[:500] if description else ""

            item = RawItem.create(
                source="rss",
                source_name=feed_name,
                title=title.strip(),
                url=link.strip(),
                body=body,
                author=author.strip() if author else "",
                published_at=self._parse_date(pub_date),
                tags=[],
                metadata={"feed_url": feed_url},
            )
            items.append(item)

        self._logger.info(f"{feed_name}: {len(items)} items", extra={"feed": feed_name, "items": len(items)})
        return items

    def _parse_atom(self, root: ET.Element, feed_url: str, feed_name: str) -> list[RawItem]:
        """Parse Atom 1.0 format."""
        items: list[RawItem] = []
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for entry in root.findall("atom:entry", ns):
            title = self._get_text(entry, "atom:title", ns)
            link_elem = entry.find("atom:link", ns)
            link = link_elem.get("href", "") if link_elem is not None else ""
            summary = self._get_text(entry, "atom:summary", ns) or self._get_text(entry, "atom:content", ns)
            updated = self._get_text(entry, "atom:updated", ns) or self._get_text(entry, "atom:published", ns)
            author_elem = entry.find("atom:author/atom:name", ns)
            author = author_elem.text if author_elem is not None and author_elem.text else ""

            if not title or not link:
                continue

            body = self._strip_html(summary)[:500] if summary else ""

            item = RawItem.create(
                source="rss",
                source_name=feed_name,
                title=title.strip(),
                url=link.strip(),
                body=body,
                author=author.strip(),
                published_at=self._parse_iso_date(updated),
                tags=[],
                metadata={"feed_url": feed_url, "format": "atom"},
            )
            items.append(item)

        self._logger.info(f"{feed_name}: {len(items)} items (Atom)", extra={"feed": feed_name, "items": len(items)})
        return items

    @staticmethod
    def _get_text(elem: ET.Element, tag: str, ns: dict | None = None) -> str:
        """Safely get text from an element."""
        if ns:
            child = elem.find(tag, ns)
        else:
            child = elem.find(tag)
        return child.text if child is not None and child.text else ""

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML tags from text."""
        import re
        clean = re.sub(r"<[^>]+>", "", text)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    @staticmethod
    def _parse_date(date_str: str | None) -> str | None:
        """Parse RFC 2822 date to ISO 8601."""
        if not date_str:
            return None
        try:
            dt = parsedate_to_datetime(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except Exception:
            return date_str

    @staticmethod
    def _parse_iso_date(date_str: str | None) -> str | None:
        """Parse ISO 8601 date (Atom format)."""
        if not date_str:
            return None
        try:
            # Try parsing as ISO 8601
            return datetime.fromisoformat(date_str.replace("Z", "+00:00")).isoformat()
        except Exception:
            return date_str
