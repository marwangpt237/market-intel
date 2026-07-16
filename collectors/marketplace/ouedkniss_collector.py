"""
Ouedkniss Collector — Algerian classifieds platform (ouedkniss.com).

The largest Algerian classifieds site. Sources:
  - Real estate listings
  - Vehicle listings
  - Job postings
  - Product listings (electronics, clothing, etc.)
  - Services

Note: Ouedkniss doesn't provide an official public RSS API, so we scrape
the public listing pages. This is best-effort and may break if they
change their HTML structure.

Config:
  categories: list of category slugs (default: all major categories)
  max_items: int (default 50)
  wilaya_filter: optional wilaya code (e.g. "DZ-16" for Alger)
"""
from __future__ import annotations

from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import re
from html.parser import HTMLParser
from core.models import RawItem
from collectors.marketplace.base import MarketplaceCollector, CollectorMetadata


class OuedknissHTMLParser(HTMLParser):
    """Simple HTML parser to extract listing data from Ouedkniss pages."""

    def __init__(self):
        super().__init__()
        self.listings: list[dict] = []
        self._current_listing: dict | None = None
        self._in_title = False
        self._in_price = False
        self._in_location = False
        self._in_link = False
        self._current_tag = ""
        self._current_attrs: dict = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._current_tag = tag
        self._current_attrs = dict(attrs)

        # Detect listing containers (Ouedkniss uses various class patterns)
        class_attr = self._current_attrs.get("class", "")
        if class_attr and ("annonce" in class_attr or "listing" in class_attr or "card" in class_attr):
            if self._current_listing is None:
                self._current_listing = {"title": "", "url": "", "price": "", "location": ""}

        # Title
        if tag == "h2" or tag == "h3":
            self._in_title = True

        # Link
        if tag == "a" and self._current_listing is not None:
            href = self._current_attrs.get("href", "")
            if href and ("/annonce/" in href or "/listing/" in href or "/product/" in href):
                if not self._current_listing["url"]:
                    self._current_listing["url"] = href
                    if href.startswith("/"):
                        self._current_listing["url"] = f"https://www.ouedkniss.com{href}"
                self._in_link = True

        # Price
        if "price" in class_attr or "prix" in class_attr:
            self._in_price = True

        # Location
        if "location" in class_attr or "wilaya" in class_attr:
            self._in_location = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("h2", "h3"):
            self._in_title = False
        if tag == "a":
            self._in_link = False
        if "price" in (self._current_attrs.get("class") or ""):
            self._in_price = False
        if "location" in (self._current_attrs.get("class") or ""):
            self._in_location = False

        # End of listing card
        if tag in ("div", "article", "li") and self._current_listing:
            if self._current_listing.get("title") or self._current_listing.get("url"):
                self.listings.append(self._current_listing)
            self._current_listing = None

    def handle_data(self, data: str) -> None:
        data = data.strip()
        if not data or not self._current_listing:
            return

        if self._in_title and not self._current_listing["title"]:
            self._current_listing["title"] = data[:200]
        elif self._in_link and not self._current_listing["title"]:
            self._current_listing["title"] = data[:200]
        elif self._in_price and not self._current_listing["price"]:
            self._current_listing["price"] = data
        elif self._in_location and not self._current_listing["location"]:
            self._current_listing["location"] = data


class OuedknissCollector(MarketplaceCollector):
    """Ouedkniss.com — Algerian classifieds platform.

    Scrapes public listing pages. Best-effort — may break if HTML structure changes.
    For production use, consider getting an official API key from Ouedkniss.
    """
    metadata = CollectorMetadata(
        name="ouedkniss",
        country="DZ",
        category="classifieds",
        entity_types=["product", "real_estate", "vehicle", "job", "service"],
        description="Ouedkniss.com — largest Algerian classifieds platform (real estate, vehicles, jobs, products)",
        rate_limit_per_hour=30,          # be respectful
        reliability=0.65,                # user-generated content, varies
        cost_per_call=0.0,
        required_credentials=[],         # no API key needed for public pages
        tags=["algeria", "classifieds", "marketplace", "ouedkniss", "dz"],
    )

    BASE_URL = "https://www.ouedkniss.com"

    # Major category slugs on Ouedkniss
    CATEGORIES = {
        "immobilier": "Real Estate",
        "automobile": "Vehicles",
        "emploi": "Jobs",
        "high-tech": "Electronics",
        "mode": "Fashion",
        "maison": "Home",
        "services": "Services",
    }

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._categories: list[str] = self._config.get("categories", list(self.CATEGORIES.keys())[:4])
        self._max_items: int = int(self._config.get("max_items", 50))
        self._wilaya_filter: str | None = self._config.get("wilaya_filter")

    def collect(self) -> list[RawItem]:
        items: list[RawItem] = []
        for category in self._categories:
            try:
                category_items = self._fetch_category(category)
                items.extend(category_items)
                if len(items) >= self._max_items:
                    break
            except Exception as e:
                self._logger.error(f"Failed to fetch Ouedkniss category '{category}': {e}")

        # Cap at max_items
        items = items[: self._max_items]
        self._logger.info(f"Ouedkniss: collected {len(items)} items from {len(self._categories)} categories")
        return items

    def _fetch_category(self, category: str) -> list[RawItem]:
        """Fetch listings from a category page."""
        url = f"{self.BASE_URL}/{category}"
        if self._wilaya_filter:
            url += f"?wilaya={self._wilaya_filter}"

        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        })

        try:
            with urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except (URLError, HTTPError) as e:
            self._logger.warning(f"Ouedkniss HTTP error for '{category}': {e}")
            return []

        # Parse HTML
        parser = OuedknissHTMLParser()
        try:
            parser.feed(html)
        except Exception as e:
            self._logger.warning(f"Ouedkniss HTML parse error: {e}")
            return []

        # Convert to RawItem
        items: list[RawItem] = []
        category_label = self.CATEGORIES.get(category, category)
        for listing in parser.listings:
            title = listing.get("title", "").strip()
            url = listing.get("url", "").strip()
            if not title or not url:
                continue

            # Combine price + location into body
            body_parts = []
            if listing.get("price"):
                body_parts.append(f"Price: {listing['price']}")
            if listing.get("location"):
                body_parts.append(f"Location: {listing['location']}")

            items.append(RawItem.create(
                source="ouedkniss",
                source_name=f"Ouedkniss — {category_label}",
                title=title,
                url=url,
                body=" | ".join(body_parts),
                author=None,
                published_at=None,
                tags=[category, "algeria", "classifieds"],
            ))

        return items
