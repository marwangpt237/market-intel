"""
Seasonal Detector — detects seasonal commerce patterns in Algeria.

Algerian e-commerce has strong seasonal cycles:
  - Ramadan (Ramadan / رمضان) — food, prayer items, gifts, clothing
  - Aid El Fitr (Eid al-Fitr / عيد الفطر) — clothing, gifts, food
  - Aid El Adha (Eid al-Adha / عيد الأضحى) — sheep/livestock, butchering equipment
  - Back-to-School (Rentrée scolaire / العودة المدرسية) — supplies, bags, uniforms
  - Summer (Été / صيف) — beach items, AC, fans, travel
  - Winter (Hiver / شتاء) — heaters, blankets, warm clothing
  - New Year / Year-end (Nouvel An / رأس السنة) — gifts, decorations
  - Independence Day (July 5) — national items, flags
  - November Revolution (November 1) — national items

Tags each item with:
  metadata["algeria"]["seasonal"] = {
    "seasons": ["ramadan", "aid_el_fitr"],
    "seasonal_score": 0.7,  # 0-1 strength of seasonal signal
    "suggested_timing": "ramadan_campaign",
  }
"""
from __future__ import annotations
import re
from datetime import datetime, timezone
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


# Seasonal patterns — (season_id, [regex patterns], [keywords], weight)
_SEASONAL_PATTERNS: list[tuple[str, list[str], list[str], int]] = [
    # Ramadan (highest commerce impact in Algeria)
    ("ramadan", [r"\bRamadan\b", r"\bرمضان\b", r"\bرمضان كريم\b"], ["ramadan", "رمضان", "ftour", "إفطار", "iftar"], 5),

    # Aid El Fitr (end of Ramadan)
    ("aid_el_fitr", [r"\bAïd El Fitr\b", r"\bAid El Fitr\b", r"\bEid al-Fitr\b", r"\bعيد الفطر\b", r"\bAïd Seghir\b"], ["aid el fitr", "عيد الفطر"], 5),

    # Aid El Adha (sheep / livestock / butchering)
    ("aid_el_adha", [r"\bAïd El Adha\b", r"\bAid El Adha\b", r"\bEid al-Adha\b", r"\bعيد الأضحى\b", r"\bAïd El Kébir\b", r"\bك deriving\b"], ["aid el adha", "عيد الأضحى", "kbir", "kbir", "sheep", "خروف"], 5),

    # Back-to-school
    ("back_to_school", [r"\brentrée scolaire\b", r"\bback[- ]to[- ]school\b", r"\bretour des classes\b", r"\bالعودة المدرسية\b"], ["rentree", "back to school", "école", "مدرسة", "cartable", "fourniture"], 4),

    # Summer
    ("summer", [r"\bété\b", r"\bsummer\b", r"\bصيف\b", r"\bvacances d'été\b"], ["été", "summer", "صيف", "plage", "beach", "م افر"], 3),

    # Winter
    ("winter", [r"\bhiver\b", r"\bwinter\b", r"\bشتاء\b"], ["hiver", "winter", "شتاء", "chauffage", "heater"], 3),

    # Year-end / New Year
    ("year_end", [r"\bNouvel An\b", r"\bNew Year\b", r"\bرأس السنة\b", r"\bfêtes de fin d'année\b"], ["nouvel an", "new year", "noël", "christmas"], 2),

    # Independence Day (July 5)
    ("independence_day", [r"\bIndépendance\b", r"\bاستقلال\b", r"\b5 juillet\b", r"\bFête de l'Indépendance\b"], ["indépendance", "5 juillet", "استقلال"], 3),

    # November 1 Revolution
    ("november_revolution", [r"\b1er Novembre\b", r"\bToussaint\b", r"\bثورة أول نوفمبر\b", r"\b1 novembre\b"], ["1er novembre", "toussaint", "1 novembre"], 2),

    # Weekly patterns (Friday prayers, weekend sales)
    ("friday", [r"\bVendredi\b", r"\bجمعة\b", r"\bFriday\b"], ["vendredi", "friday", "جمعة"], 1),
]


# Products typically associated with each season
_SEASONAL_PRODUCTS: dict[str, list[str]] = {
    "ramadan": ["dates", "dattes", "lmhajeb", "msmen", "bourek", "chorba", "hrs", "jambe", "lait", "oeufs", "تمر", "حلويات"],
    "aid_el_fitr": ["clothing", "vetements", "robe", "costume", "chaussures", "cadeaux", "ملابس", "هدايا"],
    "aid_el_adha": ["sheep", "mouton", "خروف", "khebch", "couteau", "knife", "butcher", " butcher"],
    "back_to_school": ["cartable", "sac à dos", "fournitures", "cahier", "stylo", "uniforme", "livre", "كتب", "محفظة"],
    "summer": ["clim", "climatiseur", "fan", "ventilateur", "maillot", "bikini", "lunettes", "crème solaire", "مكيف", "مروحة"],
    "winter": ["chauffage", "radiateur", "couverture", "blanket", "manteau", "veste", "مدفأة", "بطانية"],
    "year_end": ["cadeau", "gift", "décoration", "sapin", "هدايا", "زينة"],
}


class SeasonalDetector(BaseProcessor):
    """Detects seasonal commerce patterns in Algerian items."""
    name = "seasonal_detector"

    def __init__(self, config: dict | None = None):
        super().__init__(config)

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        # Compute current seasonal context (based on UTC date)
        current_season = self._get_current_season()

        for item in items:
            text = f"{item.title or ''} {item.body or ''}"

            found_seasons: list[str] = []
            seasonal_score = 0
            seasonal_products: list[str] = []

            text_lower = text.lower()

            for season_id, patterns, keywords, weight in _SEASONAL_PATTERNS:
                matched = False
                for pattern in patterns:
                    if re.search(pattern, text, re.IGNORECASE):
                        matched = True
                        break
                if not matched:
                    for kw in keywords:
                        if kw in text_lower:
                            matched = True
                            break

                if matched:
                    found_seasons.append(season_id)
                    seasonal_score += weight
                    # Check for seasonal products
                    for product in _SEASONAL_PRODUCTS.get(season_id, []):
                        if product in text_lower:
                            if product not in seasonal_products:
                                seasonal_products.append(product)

            # Boost score if the season matches current real-world season
            if current_season in found_seasons:
                seasonal_score += 3  # in-season bonus

            if found_seasons:
                if "algeria" not in item.metadata:
                    item.metadata["algeria"] = {}
                item.metadata["algeria"]["seasonal"] = {
                    "seasons": found_seasons,
                    "seasonal_score": min(20, seasonal_score),  # cap at 20
                    "seasonal_products": seasonal_products,
                    "in_season": current_season in found_seasons,
                    "current_season": current_season,
                }

        tagged = sum(1 for i in items if i.metadata.get("algeria", {}).get("seasonal"))
        self._logger.info(
            f"Seasonal detector: {tagged}/{len(items)} items have seasonal signals, current season: {current_season}"
        )
        return items

    @staticmethod
    def _get_current_season() -> str:
        """Get the current seasonal context based on current date.

        Note: Ramadan and Aid dates vary each year (lunar calendar).
        For 2026:
          - Ramadan: ~Feb 18 - Mar 19
          - Aid El Fitr: ~Mar 20
          - Aid El Adha: ~May 27
        """
        now = datetime.now(timezone.utc)
        month = now.month
        day = now.day

        # 2026 Ramadan approximation (Feb 18 - Mar 19)
        if (month == 2 and day >= 18) or (month == 3 and day <= 19):
            return "ramadan"
        # Aid El Fitr (~Mar 20-22)
        if month == 3 and 20 <= day <= 22:
            return "aid_el_fitr"
        # Aid El Adha (~May 27-30)
        if month == 5 and 27 <= day <= 30:
            return "aid_el_adha"
        # Back-to-school (Aug 15 - Sep 15)
        if (month == 8 and day >= 15) or (month == 9 and day <= 15):
            return "back_to_school"
        # Summer (Jun 21 - Sep 21)
        if month in (6, 7, 8) or (month == 9 and day <= 21):
            return "summer"
        # Winter (Dec 21 - Mar 20)
        if month == 12 or month in (1, 2) or (month == 3 and day < 20):
            return "winter"
        # Year-end (Dec 20 - Jan 5)
        if (month == 12 and day >= 20) or (month == 1 and day <= 5):
            return "year_end"
        # Independence Day (Jul 4-6)
        if month == 7 and 4 <= day <= 6:
            return "independence_day"
        # November 1 Revolution
        if month == 11 and day == 1:
            return "november_revolution"

        return "general"
