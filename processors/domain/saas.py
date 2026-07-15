"""
SaaS domain module — extracts SaaS-specific signals.

Signals detected:
  - pricing_complaint: "expensive", "overpriced", "too costly", "rip off"
  - churn_mention: "leaving", "switching from", "cancelling", "migrating away"
  - integration_request: "API for", "integration with", "connects to", "Zapier"
  - mrr_arr_mention: "MRR", "ARR", "monthly recurring", "annual revenue"
  - feature_request: "wish it had", "need a feature", "would pay for"
  - nps_positive: "love this tool", "best X ever", "game changer"
  - nps_negative: "hate this", "worst experience", "trash", "garbage"
  - onboarding_pain: "hard to set up", "confusing UI", "steep learning curve"
  - support_complaint: "no response", "support is useless", "ticket open for"
  - data_lockin: "can't export", "locked in", "no API access", "data export"

Each signal contributes to a severity score:
  high   = pricing_complaint + churn_mention + data_lockin
  medium = feature_request + integration_request + support_complaint
  low    = nps_positive + nps_negative + onboarding_pain
"""
from __future__ import annotations
import re
from core.models import ProcessedItem
from processors.domain.base import BaseDomainModule


# Signal patterns — (signal_name, regex, severity_weight)
_SAAS_PATTERNS: list[tuple[str, str, int]] = [
    # Pricing / churn (HIGH severity — direct revenue signal)
    ("pricing_complaint", r"\b(expensive|overpriced|too costly|rip[- ]?off|pricing is (insane|crazy|ridiculous))\b", 3),
    ("churn_mention", r"\b(leaving|switching from|cancelling|canceling|migrating away|moving away from|dropping)\b", 3),
    ("data_lockin", r"\b(can'?t export|locked in|no api access|data export (broken|missing)|vendor lock[- ]?in)\b", 3),
    ("downgrade_request", r"\b(downgrade|cheaper plan|lower tier|free tier)\b", 2),

    # Feature / integration (MEDIUM — growth signal)
    ("feature_request", r"\b(wish (it|they) had|need a feature|would pay for|missing feature|if only (it|they))\b", 2),
    ("integration_request", r"\b(api for|integration with|connects to|zapier|webhook support|native integration|\w+ integration)\b", 2),
    ("support_complaint", r"\b(no response|support is (useless|terrible|awful)|ticket open for|waiting on support)\b", 2),
    ("alternative_seeking", r"\b(alternative to|instead of|better than|cheaper than|replacing|looking for.*alternative|need.*alternative)\b", 2),

    # NPS / UX (LOW — sentiment signal)
    ("nps_positive", r"\b(love this (tool|app|platform)|best \w+ ever|game changer|amazing product)\b", 1),
    ("nps_negative", r"\b(hate this|worst experience|trash|garbage|useless|waste of money)\b", 1),
    ("onboarding_pain", r"\b(hard to set up|confusing (ui|interface)|steep learning curve|onboarding (sucks|is terrible))\b", 1),
    ("performance_complaint", r"\b(slow|laggy|buggy|crashes|downtime|outage)\b", 1),

    # Revenue signals (HIGH — buying intent)
    ("mrr_arr_mention", r"\b(mrr|arr|monthly recurring|annual (revenue|run rate)|\$\d+k?\s*\/?\s*mo)\b", 3),
    ("evaluation", r"\b(evaluating|comparing|testing|trial|demo|poc|proof of concept)\b", 2),
    ("budget_signal", r"\b(budget (of|is)|allocated|approved for|have \$(\d+)k? (for|to spend))\b", 3),
]


class SaaSDomainModule(BaseDomainModule):
    domain_name = "saas"

    def extract(self, item: ProcessedItem) -> dict:
        text = f"{item.title or ''} {item.body or ''}".lower()
        if not text.strip():
            return {"signals": [], "severity": "none", "entities": {}}

        signals: list[str] = []
        severity_score = 0

        for signal_name, pattern, weight in _SAAS_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                signals.append(signal_name)
                severity_score += weight

        # Map severity score to label
        if severity_score >= 6:
            severity = "high"
        elif severity_score >= 3:
            severity = "medium"
        elif severity_score >= 1:
            severity = "low"
        else:
            severity = "none"

        # Extract SaaS-specific entities (subscription tiers, dollar amounts)
        entities: dict = {}
        # Pricing mentions: $9.99/mo, $99/month, etc.
        price_matches = re.findall(r"\$(\d+(?:\.\d+)?)\s*(?:\/|per)?\s*(mo|month|year|yr)", text)
        if price_matches:
            entities["mentioned_prices"] = [float(p[0]) for p in price_matches]

        # MRR/ARR figures: $10k MRR, 50k ARR
        mrr_matches = re.findall(r"\$?(\d+(?:\.\d+)?)\s*k?\s*(mrr|arr)", text, re.IGNORECASE)
        if mrr_matches:
            entities["revenue_figures"] = [{"amount": float(m[0]), "type": m[1].upper()} for m in mrr_matches]

        return {
            "signals": signals,
            "severity": severity,
            "severity_score": severity_score,
            "entities": entities,
        }
