"""
Payment Method Detector — extracts Algerian payment method mentions.

Detects mentions of:
  - CCP (Compte Courant Postal) — Algeria Post current account
  - BaridiMob — Algeria Post mobile banking app
  - Edahabia — Algeria Post bank card
  - CIB — Carte Interbancaire (interbank card)
  - CPA — Crédit Populaire d'Algérie
  - BNA — Banque Nationale d'Algérie
  - BEA — Banque Extérieure d'Algérie
  - AGB — Alger Gulf Bank
  - Trust Bank / TrustBank
  - Assurance / Assurance CPA
  - Espèces / Cash (cash on delivery)
  - Versement (deposit)
  - PayPal (international — flagged for cross-border signals)

Tags each item with:
  metadata["algeria"]["payment_methods"] = ["ccp", "edahabia", "cash"]
  metadata["algeria"]["payment_details"] = {"ccp_account_numbers": ["1234567"], ...}
"""
from __future__ import annotations
import re
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


# Payment method patterns
# Each: (method_id, [regex_patterns], [keywords], category)
_PAYMENT_METHODS: list[tuple[str, list[str], list[str], str]] = [
    # Algeria Post (most common)
    ("ccp", [r"\bCCP\b", r"\bcompte courant postal\b"], ["ccp"], "algeria_post"),
    ("baridimob", [r"\bBaridiMob\b", r"\bBaridi Mob\b", r"\bbaridimob\b"], ["baridimob", "baridi mob"], "algeria_post"),
    ("edahabia", [r"\bEdahabia\b", r"\bEddahabia\b", r"\bEdahabia card\b", r"\bcarte Edahabia\b"], ["edahabia"], "algeria_post"),
    ("poste", [r"\bAlgérie Poste\b", r"\bAlgerie Poste\b", r"\bposte algérienne\b"], ["algérie poste"], "algeria_post"),

    # Banks
    ("cib", [r"\bCIB\b", r"\bCarte Interbancaire\b"], ["cib"], "bank_card"),
    ("cpa", [r"\bCPA\b", r"\bCrédit Populaire d'Algérie\b", r"\bCredit Populaire d'Algerie\b"], ["cpa"], "bank"),
    ("bna", [r"\bBNA\b", r"\bBanque Nationale d'Algérie\b"], ["bna"], "bank"),
    ("bea", [r"\bBEA\b", r"\bBanque Extérieure d'Algérie\b"], ["bea"], "bank"),
    ("agb", [r"\bAGB\b", r"\bAlger Gulf Bank\b"], ["agb"], "bank"),
    ("bdl", [r"\bBDL\b", r"\bBanque de Développement Local\b"], ["bdl"], "bank"),
    ("bnb", [r"\bBNB\b", r"\bBanque Nationale de Béjaïa\b"], ["bnb"], "bank"),

    # Cash / in-person
    ("cash", [r"\bcash\b", r"\bargent\b", r"\bمن يد ليد\b", r"\bكاش\b"], ["cash", "argent"], "cash"),
    ("cod", [r"\bCash on Delivery\b", r"\bCOD\b", r"\bpaiement à la livraison\b", r"\bليفريسون مقابل الدفع\b"], ["cod"], "cash"),
    ("especes", [r"\bespèces\b", r"\bفي مكان\b"], ["espèces"], "cash"),

    # Deposits / transfers
    ("versement", [r"\bversement\b", r"\bإيداع\b"], ["versement"], "transfer"),
    ("virement", [r"\bvirement\b", r"\bتحويل بنكي\b"], ["virement"], "transfer"),

    # International (flagged as cross-border signal)
    ("paypal", [r"\bPayPal\b", r"\bPaypal\b"], ["paypal"], "international"),
    ("western_union", [r"\bWestern Union\b", r"\bWesternUnion\b"], ["western union"], "international"),
    ("moneygram", [r"\bMoneyGram\b"], ["moneygram"], "international"),

    # Crypto (emerging in Algeria)
    ("bitcoin", [r"\bBitcoin\b", r"\bBTC\b", r"\bبيتكوين\b"], ["bitcoin", "btc"], "crypto"),
    ("usdt", [r"\bUSDT\b", r"\bTether\b"], ["usdt"], "crypto"),
    ("binance", [r"\bBinance\b"], ["binance"], "crypto"),
]


# CCP account number pattern (typically 8-12 digits) — flexible: matches after CCP mention with optional words in between
_CCP_ACCOUNT_PATTERN = re.compile(r"\bCCP\s*[:\s]*(?:compte\s+)?(\d{8,12})\b", re.IGNORECASE)
# Generic account number (after "compte" or "رقم")
_GENERIC_ACCOUNT_PATTERN = re.compile(r"\b(?:compte|رقم|account)\s*:?\s*(\d{8,12})\b", re.IGNORECASE)
# Phone number pattern (Algerian mobile starts with 0 then 5/6/7, 9 digits)
_DZ_PHONE_PATTERN = re.compile(r"\b0[567]\d{8}\b")


class PaymentMethodDetector(BaseProcessor):
    """Detects Algerian payment method mentions in items."""
    name = "payment_method_detector"

    def __init__(self, config: dict | None = None):
        super().__init__(config)

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        for item in items:
            text = f"{item.title or ''} {item.body or ''}"

            found_methods: list[str] = []
            found_categories: set[str] = set()
            details: dict[str, list] = {
                "ccp_account_numbers": [],
                "phone_numbers": [],
                "international_methods": [],
            }

            for method_id, patterns, keywords, category in _PAYMENT_METHODS:
                matched = False
                for pattern in patterns:
                    if re.search(pattern, text, re.IGNORECASE):
                        matched = True
                        break
                if not matched:
                    text_lower = text.lower()
                    for kw in keywords:
                        if kw in text_lower:
                            matched = True
                            break

                if matched:
                    found_methods.append(method_id)
                    found_categories.add(category)
                    if category == "international":
                        details["international_methods"].append(method_id)

            # Extract CCP account numbers
            for m in _CCP_ACCOUNT_PATTERN.finditer(text):
                details["ccp_account_numbers"].append(m.group(1))

            # Extract phone numbers (for contact / cash-on-delivery coordination)
            for m in _DZ_PHONE_PATTERN.finditer(text):
                details["phone_numbers"].append(m.group(0))

            if found_methods:
                if "algeria" not in item.metadata:
                    item.metadata["algeria"] = {}
                item.metadata["algeria"]["payment_methods"] = found_methods
                item.metadata["algeria"]["payment_categories"] = sorted(found_categories)
                item.metadata["algeria"]["payment_details"] = details

        tagged = sum(1 for i in items if i.metadata.get("algeria", {}).get("payment_methods"))
        self._logger.info(
            f"Payment detector: {tagged}/{len(items)} items tagged with payment methods"
        )
        return items
