"""
Darija NLP Processor — handles Algerian Arabic (Darija) + French + mixed text.

Detects:
  - Language mix (Arabic script chars / French Latin / Darija-specific terms)
  - Common Darija phrases used in commerce (selling, buying, complaints)
  - Algerian-specific expressions ("wesh", "khouya", "chabki", "knouz")
  - Code-switching patterns (mixing Arabic + French mid-sentence)

Tags each item with:
  metadata["algeria"]["language"] = {
    "arabic_ratio": 0.45,
    "french_ratio": 0.30,
    "darija_terms_count": 8,
    "language_mix": "arabic_french",  # arabic_only, french_only, darija_french, arabic_french, mixed
    "detected_phrases": ["بيع", "wesh", "knouz"],
  }
"""
from __future__ import annotations
import re
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


# Common Darija terms used in e-commerce / commerce contexts
# (Latin-alphabet transliterations + Arabic script)
_DARIJA_COMMERCE_PHRASES: dict[str, str] = {
    # Selling / buying
    "بيع": "selling",
    "نبيع": "selling",
    "نشري": "buying",
    "شراء": "buying",
    "knouz": "buying",       # Darija for "I want to buy"
    "chabki": "buying",      # Darija "you buy?"
    "b3t": "selling",        # SMS-style "ba3t" = sell
    "chri": "buying",
    # Pricing
    "bchhal": "price_ask",   # Darija "how much?"
    "بشحال": "price_ask",
    "chhal": "price_ask",    # French-influenced "combien"
    "thaman": "price",
    "الثمن": "price",
    # Quality / complaints
    "mazian": "good",
    "مازيان": "good",
    "machi mazian": "bad",
    "ماشي مازيان": "bad",
    "khowarij": "defective",
    "خراب": "broken",
    "mkhasar": "damaged",
    # Location
    "khouya": "brother",      # friendly address
    "يا خويا": "brother",
    "wesh": "question",       # interrogative
    "وش": "question",
    # Trust / commitment
    "w3raytek": "trust",
    "tawakkalt": "trust",
    "malgitch": "not_found",
    "machi": "is_not",
    # Urgency
    "mb3d": "later",
    "دابا": "now",
    "daba": "now",
    # Delivery
    "livraison": "delivery",   # French loanword
    "ليفريسون": "delivery",
    "twassil": "delivery",     # Darija for delivery
    "توصيل": "delivery",
}


# French commerce terms commonly used in Algeria
_FRENCH_COMMERCE_TERMS: set[str] = {
    "vente", "achat", "prix", "livraison", "livreur", "stock", "disponible",
    "rupture", "promotion", "promo", "remise", "réduction", "qualité",
    "garantie", "neuf", "occasion", "marchand", "vendeur", "acheteur",
    "commande", "passer commande", "expédition", "expédier", "paiement",
    "payer", "cb", "espèces", "cash",
}


# Arabic script range for ratio calculation
_ARABIC_SCRIPT_RANGES = [
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),  # Arabic Supplement
    (0x08A0, 0x08FF),  # Arabic Extended-A
    (0xFB50, 0xFDFF),  # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF),  # Arabic Presentation Forms-B
]


def is_arabic_char(c: str) -> bool:
    """Check if a character is in the Arabic Unicode ranges."""
    cp = ord(c)
    for start, end in _ARABIC_SCRIPT_RANGES:
        if start <= cp <= end:
            return True
    return False


class DarijaNLPProcessor(BaseProcessor):
    """Detects Darija / Arabic / French language mix in items.

    Runs after entity extraction. Tags items with language metadata
    that downstream processors can use for language-aware analysis.
    """
    name = "darija_nlp"

    def __init__(self, config: dict | None = None):
        super().__init__(config)

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        for item in items:
            text = f"{item.title or ''} {item.body or ''}"
            if not text.strip():
                continue

            analysis = self._analyze_text(text)

            if "algeria" not in item.metadata:
                item.metadata["algeria"] = {}
            item.metadata["algeria"]["language"] = analysis

        tagged = sum(1 for i in items if i.metadata.get("algeria", {}).get("language", {}).get("darija_terms_count", 0) > 0)
        self._logger.info(
            f"Darija NLP: {tagged}/{len(items)} items have Darija terms, "
            f"{sum(1 for i in items if i.metadata.get('algeria', {}).get('language', {}).get('language_mix') == 'arabic_french')}/{len(items)} are Arabic+French mix"
        )
        return items

    def _analyze_text(self, text: str) -> dict:
        """Analyze text for language mix + Darija phrases."""
        if not text:
            return {"arabic_ratio": 0, "french_ratio": 0, "darija_terms_count": 0, "language_mix": "unknown", "detected_phrases": []}

        # Char counts (excluding whitespace + punctuation)
        total_chars = sum(1 for c in text if c.isalpha())
        if total_chars == 0:
            return {"arabic_ratio": 0, "french_ratio": 0, "darija_terms_count": 0, "language_mix": "unknown", "detected_phrases": []}

        arabic_chars = sum(1 for c in text if is_arabic_char(c))
        latin_chars = sum(1 for c in text if c.isascii() and c.isalpha())

        arabic_ratio = arabic_chars / total_chars
        latin_ratio = latin_chars / total_chars

        # Detect Darija phrases (both Arabic script + transliterated Latin)
        detected_phrases: list[str] = []
        darija_term_count = 0
        text_lower = text.lower()

        for phrase, category in _DARIJA_COMMERCE_PHRASES.items():
            # Arabic phrases: search in original text
            if any(is_arabic_char(c) for c in phrase):
                if phrase in text:
                    detected_phrases.append(phrase)
                    darija_term_count += 1
            else:
                # Latin transliteration: word-boundary search
                pattern = rf"\b{re.escape(phrase)}\b"
                if re.search(pattern, text_lower):
                    detected_phrases.append(phrase)
                    darija_term_count += 1

        # Detect French commerce terms
        french_terms_found = 0
        for term in _FRENCH_COMMERCE_TERMS:
            pattern = rf"\b{re.escape(term)}\b"
            if re.search(pattern, text_lower):
                french_terms_found += 1

        # Determine language mix
        if arabic_ratio > 0.5 and latin_ratio < 0.2:
            language_mix = "arabic_only"
        elif latin_ratio > 0.5 and arabic_ratio < 0.2:
            language_mix = "french_only" if french_terms_found > 0 else "latin_only"
        elif arabic_ratio > 0.2 and latin_ratio > 0.2:
            language_mix = "arabic_french"
        elif darija_term_count >= 3:
            language_mix = "darija_french"
        else:
            language_mix = "mixed"

        return {
            "arabic_ratio": round(arabic_ratio, 3),
            "latin_ratio": round(latin_ratio, 3),
            "darija_terms_count": darija_term_count,
            "french_terms_count": french_terms_found,
            "language_mix": language_mix,
            "detected_phrases": detected_phrases[:10],  # cap for storage
        }
