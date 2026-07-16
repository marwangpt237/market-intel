"""
Wilaya Extractor — extracts Algerian wilaya (province) mentions from text.

Recognizes 58 wilayas by:
  - French name (Alger, Oran, Constantine)
  - Arabic name (الجزائر, وهران, قسنطينة)
  - Common abbreviations (Alger = DZ-16, Oran = DZ-31)
  - City names mapped to their wilaya (Bab Ezzouar → Alger)

Output: list of wilaya codes (DZ-01 through DZ-58) detected.
"""
from __future__ import annotations
import re
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


# 58 wilayas — code, French name, Arabic name, common city aliases
# Format: (code, [french_names], [arabic_names], [city_aliases])
WILAYAS: list[tuple[str, list[str], list[str], list[str]]] = [
    ("DZ-01", ["Adrar"], ["أدرار"], []),
    ("DZ-02", ["Chlef", "El Asnam"], ["الشلف"], []),
    ("DZ-03", ["Laghouat"], ["الأغواط"], []),
    ("DZ-04", ["Oum El Bouaghi"], ["أم البواقي"], []),
    ("DZ-05", ["Batna"], ["باتنة"], []),
    ("DZ-06", ["Béjaïa", "Bejaia", "Bgayet"], ["بجاية"], []),
    ("DZ-07", ["Biskra"], ["بسكرة"], []),
    ("DZ-08", ["Béchar", "Bechar"], ["بشار"], []),
    ("DZ-09", ["Blida"], ["البليدة"], []),
    ("DZ-10", ["Bouira"], ["البويرة"], []),
    ("DZ-11", ["Tamanrasset", "Tam"], ["تمنراست"], []),
    ("DZ-12", ["Tébessa", "Tebessa"], ["تبسة"], []),
    ("DZ-13", ["Tlemcen"], ["تلمسان"], []),
    ("DZ-14", ["Tiaret"], ["تيارت"], []),
    ("DZ-15", ["Tizi Ouzou", "Tizi-Ouzou", "Tizi"], ["تيزي وزو"], []),
    ("DZ-16", ["Alger", "Alger Centre", "Bab El Oued", "Bab Ezzouar", "Hussein Dey", "Bir Mourad Raïs", "El Harrach", "Dély Ibrahim", "Birkhadem", "Kouba", "Bouzareah", "El Biar"], ["الجزائر", "الجزائر العاصمة"], ["alger", "algiers"]),
    ("DZ-17", ["Djelfa"], ["الجلفة"], []),
    ("DZ-18", ["Jijel"], ["جيجل"], []),
    ("DZ-19", ["Sétif", "Setif"], ["سطيف"], []),
    ("DZ-20", ["Saïda", "Saida"], ["سعيدة"], []),
    ("DZ-21", ["Skikda"], ["سكيكدة"], []),
    ("DZ-22", ["Sidi Bel Abbès", "Sidi Bel Abbes"], ["سيدي بلعباس"], []),
    ("DZ-23", ["Annaba"], ["عنابة"], []),
    ("DZ-24", ["Guelma"], ["قالمة"], []),
    ("DZ-25", ["Constantine", "Constantine Centre"], ["قسنطينة"], []),
    ("DZ-26", ["Médéa", "Medea"], ["المدية"], []),
    ("DZ-27", ["Mostaganem"], ["مستغانم"], []),
    ("DZ-28", ["M'Sila", "Msila", "M Sila"], ["المسيلة"], []),
    ("DZ-29", ["Mascara"], ["معسكر"], []),
    ("DZ-30", ["Ouargla"], ["ورقلة"], []),
    ("DZ-31", ["Oran", "Oran Centre", "Es Senia", "Bir El Djir", "Arzew", "Bethioua"], ["وهران"], ["oran"]),
    ("DZ-32", ["El Bayadh"], ["البيض"], []),
    ("DZ-33", ["Illizi"], ["إليزي"], []),
    ("DZ-34", ["Bordj Bou Arréridj", "Bordj Bou Arreridj", "BBA", "Bordj"], ["برج بوعريريج"], []),
    ("DZ-35", ["Boumerdès", "Boumerdes"], ["بومرداس"], []),
    ("DZ-36", ["El Tarf"], ["الطارف"], []),
    ("DZ-37", ["Tindouf"], ["تندوف"], []),
    ("DZ-38", ["Tissemsilt"], ["تيسمسيلت"], []),
    ("DZ-39", ["El Oued", "El-Oued"], ["الوادي"], []),
    ("DZ-40", ["Khenchela"], ["خنشلة"], []),
    ("DZ-41", ["Souk Ahras"], ["سوق أهراس"], []),
    ("DZ-42", ["Tipaza", "Tipaza Centre"], ["تيبازة"], []),
    ("DZ-43", ["Mila"], ["ميلة"], []),
    ("DZ-44", ["Aïn Defla", "Ain Defla"], ["عين الدفلى"], []),
    ("DZ-45", ["Naâma", "Naama"], ["النعامة"], []),
    ("DZ-46", ["Aïn Témouchent", "Ain Temouchent"], ["عين تموشنت"], []),
    ("DZ-47", ["Ghardaïa", "Ghardaia"], ["غرداية"], []),
    ("DZ-48", ["Relizane"], ["غليزان"], []),
    # New wilayas created in 2021
    ("DZ-49", ["Timimoun"], ["تيميمون"], []),
    ("DZ-50", ["Bordj Badji Mokhtar", "BBM"], ["برج باجي مختار"], []),
    ("DZ-51", ["Ouled Djellal"], ["أولاد جلال"], []),
    ("DZ-52", ["Béni Abbès", "Beni Abbes"], ["بني عباس"], []),
    ("DZ-53", ["In Salah"], ["عين صالح"], []),
    ("DZ-54", ["In Guezzam"], ["عين قزام"], []),
    ("DZ-55", ["Touggourt"], ["تقرت"], []),
    ("DZ-56", ["Djanet"], ["جانت"], []),
    ("DZ-57", ["El M'Ghair", "El Mghair"], ["المغير"], []),
    ("DZ-58", ["El Meniaa", "El Menia"], ["المنيعة"], []),
]


class WilayaExtractor(BaseProcessor):
    """Extracts Algerian wilaya mentions from item text.

    Tags each item with:
      metadata["algeria"]["wilayas"] = ["DZ-16", "DZ-31"]
      metadata["algeria"]["wilaya_names"] = ["Alger", "Oran"]
    """
    name = "wilaya_extractor"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        # Build lookup: lowercase name → wilaya code
        self._lookup: dict[str, str] = {}
        self._code_to_name: dict[str, str] = {}
        for code, french_names, arabic_names, aliases in WILAYAS:
            for name in french_names + aliases:
                self._lookup[name.lower()] = code
            for name in arabic_names:
                self._lookup[name] = code
            self._code_to_name[code] = french_names[0]

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        for item in items:
            text = f"{item.title or ''} {item.body or ''}".lower()
            # Also include original-case text for Arabic (Arabic doesn't have case)
            full_text = f"{item.title or ''} {item.body or ''}"

            found_codes: set[str] = set()
            found_names: list[str] = []

            for name, code in self._lookup.items():
                # Use word boundary for short names to avoid false matches
                if len(name) <= 4:
                    pattern = rf"\b{re.escape(name)}\b"
                    if re.search(pattern, text, re.IGNORECASE):
                        if code not in found_codes:
                            found_codes.add(code)
                            found_names.append(self._code_to_name[code])
                else:
                    if name in text or name in full_text:
                        if code not in found_codes:
                            found_codes.add(code)
                            found_names.append(self._code_to_name[code])

            # Stash on item metadata under "algeria" namespace
            if "algeria" not in item.metadata:
                item.metadata["algeria"] = {}
            item.metadata["algeria"]["wilayas"] = sorted(found_codes)
            item.metadata["algeria"]["wilaya_names"] = found_names

        self._logger.info(
            f"Wilaya extractor: {sum(1 for i in items if i.metadata.get('algeria', {}).get('wilayas'))}/{len(items)} items tagged with wilayas"
        )
        return items
