"""Jumia DZ collector — Algeria's largest e-commerce platform."""
from __future__ import annotations
from urllib.request import urlopen, Request
from html.parser import HTMLParser
import re
from core.models import RawItem
from collectors.marketplace.base import MarketplaceCollector, CollectorMetadata


class JumiaHTMLParser(HTMLParser):
    """Parse Jumia product listing pages."""
    def __init__(self):
        super().__init__()
        self.products: list[dict] = []
        self._current: dict | None = None
        self._in_name = False
        self._in_price = False
        self._in_link = False

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        cls = attrs_d.get("class", "")
        if "name" in cls and tag == "h3":
            self._in_name = True
        if "price" in cls and ("role" in attrs_d or tag in ("span", "div")):
            self._in_price = True
        if tag == "a" and attrs_d.get("href", "").startswith("/"):
            if self._current is None:
                self._current = {"title": "", "url": "", "price": ""}
            if not self._current["url"]:
                self._current["url"] = "https://www.jumia.dz" + attrs_d["href"]
            self._in_link = True
        if "product" in cls or "sku" in cls:
            if self._current is None:
                self._current = {"title": "", "url": "", "price": ""}

    def handle_data(self, data):
        data = data.strip()
        if not data or not self._current:
            return
        if self._in_name and not self._current["title"]:
            self._current["title"] = data[:200]
        elif self._in_link and not self._current["title"]:
            self._current["title"] = data[:200]
        elif self._in_price and not self._current["price"]:
            self._current["price"] = data

    def handle_endtag(self, tag):
        if tag in ("h3", "a"):
            self._in_name = False
            self._in_link = False
        if tag in ("span", "div"):
            self._in_price = False
        if tag == "article" and self._current:
            if self._current.get("title") or self._current.get("url"):
                self.products.append(self._current)
            self._current = None


class JumiaDZCollector(MarketplaceCollector):
    """Jumia.dz — Algeria's largest e-commerce platform.

    Scrapes product listings from major categories. Prices are in DZD.
    """
    metadata = CollectorMetadata(
        name="jumia_dz",
        country="DZ",
        category="marketplace",
        entity_types=["product", "price", "brand"],
        description="Jumia.dz — Algeria's largest e-commerce platform (electronics, fashion, home, beauty)",
        rate_limit_per_hour=30,
        reliability=0.80,  # structured e-commerce data — higher reliability
        cost_per_call=0.0,
        required_credentials=[],
        tags=["algeria", "ecommerce", "marketplace", "jumia", "prices", "dz"],
    )

    CATEGORIES = {
        "televisions": "Electronics",
        "smartphones": "Electronics",
        "laptops": "Electronics",
        "homme-vetements": "Fashion",
        "femme-vetements": "Fashion",
        "beaute": "Beauty",
        "maison-cuisine": "Home",
    }

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._categories: list[str] = self._config.get("categories", list(self.CATEGORIES.keys())[:4])
        self._max_items: int = int(self._config.get("max_items", 40))

    def collect(self) -> list[RawItem]:
        items: list[RawItem] = []
        for cat in self._categories:
            try:
                cat_items = self._fetch_category(cat)
                items.extend(cat_items)
                if len(items) >= self._max_items:
                    break
            except Exception as e:
                self._logger.error(f"Jumia category '{cat}' failed: {e}")
        items = items[: self._max_items]
        self._logger.info(f"Jumia DZ: collected {len(items)} products from {len(self._categories)} categories")
        return items

    def _fetch_category(self, category: str) -> list[RawItem]:
        url = f"https://www.jumia.dz/{category}/"
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept-Language": "fr-FR,fr;q=0.9",
        })
        try:
            with urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            self._logger.warning(f"Jumia HTTP error '{category}': {e}")
            return []

        parser = JumiaHTMLParser()
        try:
            parser.feed(html)
        except Exception:
            pass

        cat_label = self.CATEGORIES.get(category, category)
        items: list[RawItem] = []
        for product in parser.products:
            title = product.get("title", "").strip()
            url = product.get("url", "").strip()
            if not title or not url:
                continue
            body_parts = []
            if product.get("price"):
                body_parts.append(f"Price: {product['price']}")
            items.append(RawItem.create(
                source="jumia_dz",
                source_name=f"Jumia DZ — {cat_label}",
                title=title,
                url=url,
                body=" | ".join(body_parts),
                tags=["product", "algeria", "ecommerce", "jumia", category],
            ))
        return items
