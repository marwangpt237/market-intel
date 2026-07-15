"""
Entity extraction — identifies companies, products, and people in text.

Uses deterministic pattern matching (no AI):
1. Known company/product dictionary (extensible via config)
2. Capitalized word sequences (proper nouns)
3. Pattern-based detection (Inc., Ltd., @handles, etc.)

Extracted entities are added to ProcessedItem.metadata["entities"].
"""
from __future__ import annotations

import re
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


# Built-in dictionaries — extend via config
DEFAULT_COMPANIES = {
    "google", "microsoft", "apple", "amazon", "meta", "facebook", "instagram",
    "twitter", "linkedin", "tiktok", "youtube", "netflix", "spotify",
    "hubspot", "salesforce", "mailchimp", "semrush", "ahrefs", "moz",
    "canva", "figma", "notion", "slack", "zoom", "stripe", "shopify",
    "wordpress", "squarespace", "wix", "mailgun", "twilio",
    "maltego", "spiderfoot", "shodan", "virustotal", "hunter",
    "openai", "anthropic", "midjourney", "stability",
    "reddit", "discord", "telegram", "whatsapp",
    "adobe", "oracle", "sap", "ibm", "intel", "nvidia",
    "uber", "airbnb", "doordash", "stripe",
}

DEFAULT_PRODUCTS = {
    "chatgpt", "claude", "gemini", "copilot", "bard", "dall-e", "stable diffusion",
    "google ads", "facebook ads", "google analytics", "ga4", "search console",
    "wordpress", "shopify", "magento", "woocommerce",
    "salesforce crm", "hubspot crm", "marketo", "pardot",
    "semrush", "ahrefs", "moz pro", "screaming frog",
    "photoshop", "illustrator", "indesign", "premiere",
    "zoom", "teams", "slack", "notion", "airtable",
}

# Patterns for detecting entities
COMPANY_SUFFIX_PATTERN = re.compile(
    r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*)\s+(?:Inc\.?|LLC|Ltd\.?|Corp\.?|Corporation|Company|Co\.?|Group|Holdings)\b"
)
HANDLE_PATTERN = re.compile(r"@([a-zA-Z0-9_]{3,})")
URL_COMPANY_PATTERN = re.compile(r"https?://(?:www\.)?([a-z0-9-]+)\.(?:com|io|ai|co|org|net)")


class EntityExtractionProcessor(BaseProcessor):
    name = "entity_extraction"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._companies: set[str] = set(DEFAULT_COMPANIES) | set((config or {}).get("companies", []))
        self._products: set[str] = set(DEFAULT_PRODUCTS) | set((config or {}).get("products", []))

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        for item in items:
            text = f"{item.title} {item.body}"
            entities: dict[str, list[str]] = {"companies": [], "products": [], "people": []}

            # 1. Dictionary match (case-insensitive)
            text_lower = text.lower()
            for company in self._companies:
                if company in text_lower:
                    entities["companies"].append(company)

            for product in self._products:
                if product in text_lower:
                    entities["products"].append(product)

            # 2. Company suffix pattern (e.g., "Acme Inc.")
            for match in COMPANY_SUFFIX_PATTERN.finditer(text):
                name = match.group(1).strip()
                if name.lower() not in [c.lower() for c in entities["companies"]]:
                    entities["companies"].append(name)

            # 3. @handles (people or companies)
            for match in HANDLE_PATTERN.finditer(text):
                handle = match.group(1)
                if handle.lower() not in self._companies:
                    entities["people"].append(f"@{handle}")

            # 4. URL-based company detection
            for match in URL_COMPANY_PATTERN.finditer(text):
                domain = match.group(1)
                if domain not in ["www", "http", "https"] and domain not in [c.lower() for c in entities["companies"]]:
                    entities["companies"].append(domain)

            # Deduplicate
            entities["companies"] = list(set(entities["companies"]))
            entities["products"] = list(set(entities["products"]))
            entities["people"] = list(set(entities["people"]))[:5]  # cap people

            item.metadata["entities"] = entities

        total_entities = sum(len(item.metadata.get("entities", {}).get("companies", [])) for item in items)
        self._logger.info(
            f"Entity extraction: {len(items)} items, {total_entities} companies found",
            extra={"items": len(items), "total_companies": total_entities}
        )
        return items
