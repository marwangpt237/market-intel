"""
Algeria Product Extractor — extracts product mentions and DZD prices.

Detects:
  - Product names (clothing, electronics, home goods, food, beauty, etc.)
  - Prices in DZD (Algerian Dinar) — multiple formats:
      "3500 DZD", "3500 DA", "3500 dinars", "3500 دج", "3500 دينار"
  - Price ranges ("entre 3000 et 5000 DA")
  - Discount mentions ("promo", "remise", "réduction", "خصم")
  - Stock status ("en stock", "rupture", "épuisé", "متوفر")
  - Condition ("neuf", "occasion", "جديد", "مستعمل")
  - Brand mentions (Adidas, Nike, Apple, Samsung, Huawei, Xiaomi, etc.)

Tags each item with:
  metadata["algeria"]["products"] = [
    {
      "name": "backpack",
      "category": "bags",
      "price_dzd": 3800,
      "price_range": [3000, 4500],
      "condition": "neuf",
      "in_stock": True,
      "discount_pct": 20,
      "brand": null,
    },
    ...
  ]
"""
from __future__ import annotations
import re
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


# Product category keywords (lowercase) — Algerian commerce context
_PRODUCT_CATEGORIES: dict[str, list[str]] = {
    "clothing": ["robe", "veste", "manteau", "pantalon", "chemise", "tshirt", "t-shirt", "pull", "gilet", "jupe", "short", "blouse", "habit", "vetement", "vêtement", "ملابس", "قفطان", "robe algérienne", "burnous", "kachabia"],
    "shoes": ["chaussures", "baskets", "sandales", "mocassins", "bottes", "escarpins", "sneakers", "حذاء", "صبير"],
    "bags": ["sac", "sac à dos", "cartable", "sac à main", "valise", "حقيبة", "محفظة"],
    "accessories": ["montre", "lunettes", "ceinture", "foulard", "écharpe", "chapeau", "casquette", "bijoux", "montre", "ساعة", "نظارات"],
    "beauty": ["parfum", "maquillage", "crème", "shampooing", "cosmétique", "rouge à lèvres", "mascara", "عطر", "مكياج"],
    "electronics": ["téléphone", "telephone", "smartphone", "iphone", "samsung", "huawei", "xiaomi", "laptop", "pc", "ordinateur", "tablette", "ipad", "console", "playstation", "xbox", "هاتف", "حاسوب"],
    "home_appliance": ["réfrigérateur", "frigo", "lave-linge", "machine à laver", "cuisinière", "four", "micro-ondes", "aspirateur", "ثلاجة", "غسالة"],
    "furniture": ["table", "chaise", "canapé", "lit", "armoire", "commode", "bureau", "مكتب", "كرسي", "طاولة"],
    "food": ["huile", "sucre", "farine", "lait", "oeufs", "oeuf", "pomme", "banane", "dattes", "café", "thé", "تمر", "حليب"],
    "kitchen": ["casserole", "poêle", "couverts", "assiettes", "verres", "marmite", "قدر", "مقلاة"],
    "beauty_devices": ["sèche-cheveux", "lisseur", "épilateur", "tondeuse", "مجفف شعر"],
    "auto": ["pneu", "jante", "batterie", "huile moteur", "pièce auto", "إطار"],
    "toys": ["jouet", "jeu", "puzzle", "poupée", "lego", "لعبة"],
    "sports": ["ballon", "raquette", "vélo", "tapis", "haltère", "كرة"],
    "books": ["livre", "cahier", "roman", "كتاب", "دفتر"],
    "school_supplies": ["stylo", "crayon", "trousse", "règle", "gomme", "قلم"],
}


# Brand → category mapping (commonly seen in Algerian commerce)
_BRAND_MAPPING: dict[str, str] = {
    "adidas": "clothing", "nike": "clothing", "puma": "clothing", "reebok": "clothing",
    "zara": "clothing", "hm": "clothing", "h&m": "clothing", "pull&bear": "clothing",
    "apple": "electronics", "samsung": "electronics", "huawei": "electronics", "xiaomi": "electronics",
    "oppo": "electronics", "realme": "electronics", "infinix": "electronics", "tecno": "electronics",
    "hp": "electronics", "dell": "electronics", "lenovo": "electronics", "asus": "electronics",
    "acer": "electronics", "msi": "electronics",
    "lg": "home_appliance", "bosch": "home_appliance", "whirlpool": "home_appliance",
    "tefal": "kitchen", "seb": "kitchen", "moulinex": "kitchen",
    "sony": "electronics", "jbl": "electronics", "beats": "electronics",
}


# Price patterns (DZD = Algerian Dinar)
# Match: "3500 DZD", "3500 DA", "3500 dinars", "3500 دج", "3500 دينار"
_PRICE_PATTERNS = [
    re.compile(r"(\d{3,6}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*(?:DZD|DA|dinars?|دج|دينار)\b", re.IGNORECASE),
    re.compile(r"(?:DZD|DA|dinars?|دج|دينار)\s*(\d{3,6}(?:[.,]\d{3})*)", re.IGNORECASE),
    re.compile(r"(\d{3,6})\s*(?:DA|دج)\b", re.IGNORECASE),
]

# Price range pattern: "entre 3000 et 5000 DA" / "from 3000 to 5000 DZD"
_PRICE_RANGE_PATTERN = re.compile(
    r"(?:entre|from|de|between)\s*(\d{3,6})\s*(?:et|and|à|to|-)\s*(\d{3,6})\s*(?:DZD|DA|dinars?|دج|دينار)?",
    re.IGNORECASE,
)

# Discount patterns
_DISCOUNT_PATTERNS = [
    (re.compile(r"(\d+)\s*%\s*(?:de\s*)?(?:remise|réduction|promo|discount)", re.IGNORECASE), "percent"),
    (re.compile(r"promo(?:tion)?\s*[:\-]?\s*(\d+)\s*%", re.IGNORECASE), "percent"),
    (re.compile(r"[-−](\d+)\s*%", re.IGNORECASE), "percent"),
    (re.compile(r"(\d+)\s*%\s*(?:off|de remise)", re.IGNORECASE), "percent"),
]

# Stock patterns
_IN_STOCK_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r"\ben stock\b", r"\bdisponible\b", r"\bavailable\b", r"\bمتوفر\b", r"\bموجود\b",
]]
_OUT_OF_STOCK_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r"\brupture\b", r"\bépuisé\b", r"\bepuise\b", r"\bout of stock\b", r"\bnon disponible\b", r"\bنفد\b", r"\bغير متوفر\b",
]]

# Condition patterns
_CONDITION_PATTERNS = {
    "new": [re.compile(p, re.IGNORECASE) for p in [r"\bneuf\b", r"\bnouveau\b", r"\bnew\b", r"\bجديد\b"]],
    "used": [re.compile(p, re.IGNORECASE) for p in [r"\boccasion\b", r"\bused\b", r"\bمستعمل\b", r"\bقديم\b"]],
}


def _parse_price(price_str: str) -> int | None:
    """Parse a price string into an integer DZD amount."""
    if not price_str:
        return None
    # Remove thousand separators (commas, dots, spaces)
    cleaned = re.sub(r"[.,\s](?=\d{3})", "", price_str)
    # If there's a remaining dot/comma, it might be decimal — drop it
    cleaned = cleaned.replace(".", "").replace(",", "")
    try:
        return int(cleaned)
    except ValueError:
        return None


class AlgeriaProductExtractor(BaseProcessor):
    """Extracts product mentions + DZD prices from items."""
    name = "algeria_product_extractor"

    def __init__(self, config: dict | None = None):
        super().__init__(config)

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        for item in items:
            text = f"{item.title or ''} {item.body or ''}"
            text_lower = text.lower()

            products_found: list[dict] = []

            # Detect product categories
            for category, keywords in _PRODUCT_CATEGORIES.items():
                for kw in keywords:
                    if kw in text_lower:
                        # Found a product mention — try to extract price nearby
                        product = {
                            "name": kw,
                            "category": category,
                            "price_dzd": self._find_nearby_price(text, kw),
                            "condition": self._detect_condition(text),
                            "in_stock": self._detect_stock(text),
                            "discount_pct": self._detect_discount(text),
                            "brand": self._detect_brand(text_lower, category),
                        }
                        # Check for price range
                        price_range = self._detect_price_range(text)
                        if price_range:
                            product["price_range"] = price_range
                            if product["price_dzd"] is None:
                                # Use range midpoint as price
                                product["price_dzd"] = (price_range[0] + price_range[1]) // 2

                        products_found.append(product)
                        break  # one match per category is enough

            if products_found:
                if "algeria" not in item.metadata:
                    item.metadata["algeria"] = {}
                item.metadata["algeria"]["products"] = products_found

        tagged = sum(1 for i in items if i.metadata.get("algeria", {}).get("products"))
        self._logger.info(
            f"Algeria product extractor: {tagged}/{len(items)} items have product mentions, "
            f"total products: {sum(len(i.metadata.get('algeria', {}).get('products', [])) for i in items)}"
        )
        return items

    def _find_nearby_price(self, text: str, keyword: str, window: int = 80) -> int | None:
        """Find a price near the keyword occurrence."""
        # Find keyword position (case-insensitive)
        idx = text.lower().find(keyword.lower())
        if idx < 0:
            return None

        # Get surrounding window
        start = max(0, idx - window)
        end = min(len(text), idx + len(keyword) + window)
        context = text[start:end]

        # Try each price pattern
        for pattern in _PRICE_PATTERNS:
            m = pattern.search(context)
            if m:
                price = _parse_price(m.group(1))
                if price and 100 <= price <= 5_000_000:  # sanity check: 100 DZD to 5M DZD
                    return price
        return None

    def _detect_price_range(self, text: str) -> tuple[int, int] | None:
        """Detect price range like 'entre 3000 et 5000 DA'."""
        m = _PRICE_RANGE_PATTERN.search(text)
        if m:
            low = _parse_price(m.group(1))
            high = _parse_price(m.group(2))
            if low and high and low < high:
                return (low, high)
        return None

    def _detect_condition(self, text: str) -> str | None:
        for pattern in _CONDITION_PATTERNS["new"]:
            if pattern.search(text):
                return "new"
        for pattern in _CONDITION_PATTERNS["used"]:
            if pattern.search(text):
                return "used"
        return None

    def _detect_stock(self, text: str) -> bool | None:
        for pattern in _OUT_OF_STOCK_PATTERNS:
            if pattern.search(text):
                return False
        for pattern in _IN_STOCK_PATTERNS:
            if pattern.search(text):
                return True
        return None

    def _detect_discount(self, text: str) -> int | None:
        for pattern, kind in _DISCOUNT_PATTERNS:
            m = pattern.search(text)
            if m:
                try:
                    pct = int(m.group(1))
                    if 5 <= pct <= 90:  # sanity check
                        return pct
                except (ValueError, IndexError):
                    continue
        return None

    def _detect_brand(self, text_lower: str, category: str) -> str | None:
        for brand, brand_category in _BRAND_MAPPING.items():
            if brand_category == category and re.search(rf"\b{re.escape(brand)}\b", text_lower):
                return brand
        return None
