"""
E-commerce domain module — extracts e-commerce-specific signals.

Signals detected:
  - shipping_complaint: "slow shipping", "never arrived", "late delivery"
  - return_issue: "return policy", "can't return", "return denied"
  - product_quality: "poor quality", "broke after", "fake product"
  - inventory_issue: "out of stock", "backorder", "restock"
  - payment_issue: "chargeback", "refund", "double charged"
  - pricing_complaint: "overpriced", "cheaper elsewhere"
  - customer_service: "no response", "rude", "unhelpful"
  - review_positive: "highly recommend", "great product", "love it"
  - review_negative: "would not recommend", "waste of money", "do not buy"
  - cart_abandonment: "abandoned cart", "checkout issue", "payment failed"
  - inventory_demand: "sold out", "viral product", "trending"
"""
from __future__ import annotations
import re
from core.models import ProcessedItem
from processors.domain.base import BaseDomainModule


_ECOMMERCE_PATTERNS: list[tuple[str, str, int]] = [
    # Fulfillment (HIGH — direct revenue impact)
    ("shipping_complaint", r"\b(slow shipping|never arrived|late delivery|shipping delay|tracking (broken|not working))\b", 3),
    ("return_issue", r"\b(return (policy|denied|issue)|can'?t return|refund (denied|delayed))\b", 3),
    ("payment_issue", r"\b(chargeback|double charg(ed|ing)|payment (failed|declined)|fraudulent (charge|order))\b", 3),
    ("product_quality", r"\b(poor quality|broke after|fake product|counterfeit|not as described)\b", 3),

    # Inventory / demand (HIGH — buying signal)
    ("inventory_demand", r"\b(sold out|out of stock|backorder|restock|viral product|trending product)\b", 3),
    ("cart_abandonment", r"\b(abandoned cart|checkout (issue|abandonment)|cart abandonment)\b", 2),

    # Pricing / competitor (MEDIUM)
    ("pricing_complaint", r"\b(overpriced|cheaper elsewhere|price (gouging|increase)|rip[- ]?off)\b", 2),
    ("competitor_mention", r"\b(vs|versus|compared to|better than|alternative to)\b.*\b(on amazon|etsy|ebay|shopify)\b", 2),

    # Reviews (LOW)
    ("review_positive", r"\b(highly recommend|great product|love it|five stars|amazing quality)\b", 1),
    ("review_negative", r"\b(would not recommend|waste of money|do not buy|one star|terrible product)\b", 1),
    ("customer_service", r"\b(no response|rude|unhelpful|worst customer service|support ticket)\b", 1),

    # Platform-specific
    ("amazon_mention", r"\bamazon\b", 1),
    ("shopify_mention", r"\bshopify\b", 1),
    ("etsy_mention", r"\betsy\b", 1),
    ("ebay_mention", r"\bebay\b", 1),

    # Logistics
    ("logistics_issue", r"\b(lost package|damaged (in transit|on arrival)|missing items|wrong item)\b", 2),
    ("warehouse_issue", r"\b(warehouse (delay|issue)|fulfillment (center|issue)|3pl)\b", 2),
]


class EcommerceDomainModule(BaseDomainModule):
    domain_name = "ecommerce"

    def extract(self, item: ProcessedItem) -> dict:
        text = f"{item.title or ''} {item.body or ''}".lower()
        if not text.strip():
            return {"signals": [], "severity": "none", "entities": {}}

        signals: list[str] = []
        severity_score = 0
        entities: dict = {}

        for signal_name, pattern, weight in _ECOMMERCE_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                signals.append(signal_name)
                severity_score += weight

                # Extract platforms mentioned
                if signal_name.endswith("_mention"):
                    platform = signal_name.replace("_mention", "")
                    if "platforms" not in entities:
                        entities["platforms"] = []
                    if platform not in entities["platforms"]:
                        entities["platforms"].append(platform)

        # Extract price mentions
        price_matches = re.findall(r"\$(\d+(?:\.\d+)?)", text)
        if price_matches:
            entities["mentioned_prices"] = [float(p) for p in price_matches[:5]]

        # Extract product-related keywords (very simple)
        product_keywords = re.findall(r"\b(best|top|cheap|affordable|premium|luxury)\s+(\w+)", text)
        if product_keywords:
            entities["product_categories"] = list(set(p[1] for p in product_keywords))[:5]

        if severity_score >= 6:
            severity = "high"
        elif severity_score >= 3:
            severity = "medium"
        elif severity_score >= 1:
            severity = "low"
        else:
            severity = "none"

        return {
            "signals": signals,
            "severity": severity,
            "severity_score": severity_score,
            "entities": entities,
        }
