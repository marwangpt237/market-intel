"""
Buying-signal detection — identifies purchase intent in collected content.

Detects:
1. Evaluation signals ("comparing", "evaluating", "testing", "trial")
2. Budget signals ("budget", "willing to pay", "$X/month", "afford")
3. Urgency signals ("need urgently", "ASAP", "this week", "deadline")
4. Decision signals ("choosing between", "deciding", "ready to buy")
5. Problem-aware signals (pain-point co-occurrence with product mentions)

Output: item.metadata["buying_signals"] = list of {type, text, confidence}
"""
from __future__ import annotations

import re
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


EVALUATION_PATTERNS = [
    re.compile(r"\b(?:comparing|evaluation|evaluating|testing|trial\w*|demo)\b", re.I),
    re.compile(r"\b(?:pros\s+and\s+cons|review|hands-on)\b", re.I),
    re.compile(r"\b(?:shortlist|finalist|top\s+\d)\b", re.I),
]

BUDGET_PATTERNS = [
    re.compile(r"\bbudget\s+(?:of|is|around)?\s*\$?\d+", re.I),
    re.compile(r"\bwilling\s+to\s+(?:pay|spend)\b", re.I),
    re.compile(r"\$\d+\s*(?:/|per\s+)?(?:month|mo|year|yr)", re.I),
    re.compile(r"\b(?:afford|affordable|cheap|free)\b", re.I),
    re.compile(r"\bpricing\s+(?:plan|tier|model)\b", re.I),
]

URGENCY_PATTERNS = [
    re.compile(r"\b(?:urgent|ASAP|immediately|right\s+away)\b", re.I),
    re.compile(r"\b(?:this\s+week|by\s+Friday|deadline|time-sensitive)\b", re.I),
    re.compile(r"\bneed\s+(?:a\s+)?(?:tool|solution|platform)\s+(?:now|quickly|fast)\b", re.I),
]

DECISION_PATTERNS = [
    re.compile(r"\b(?:choosing|deciding)\s+between\b", re.I),
    re.compile(r"\b(?:ready|about)\s+to\s+(?:buy|purchase|subscribe|sign\s+up)\b", re.I),
    re.compile(r"\b(?:final\s+decision|pull\s+the\s+trigger)\b", re.I),
]


class BuyingSignalProcessor(BaseProcessor):
    name = "buying_signal_detection"

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        total_signals = 0

        for item in items:
            text = f"{item.title} {item.body}"
            signals: list[dict] = []

            # Evaluation signals (medium confidence)
            for pattern in EVALUATION_PATTERNS:
                for match in pattern.finditer(text):
                    signals.append({
                        "type": "evaluation",
                        "text": match.group(0),
                        "confidence": 0.6,
                        "context": text[max(0, match.start()-40):match.end()+40].strip(),
                    })

            # Budget signals (high confidence)
            for pattern in BUDGET_PATTERNS:
                for match in pattern.finditer(text):
                    signals.append({
                        "type": "budget",
                        "text": match.group(0),
                        "confidence": 0.8,
                        "context": text[max(0, match.start()-40):match.end()+40].strip(),
                    })

            # Urgency signals (medium-high confidence)
            for pattern in URGENCY_PATTERNS:
                for match in pattern.finditer(text):
                    signals.append({
                        "type": "urgency",
                        "text": match.group(0),
                        "confidence": 0.7,
                        "context": text[max(0, match.start()-40):match.end()+40].strip(),
                    })

            # Decision signals (highest confidence)
            for pattern in DECISION_PATTERNS:
                for match in pattern.finditer(text):
                    signals.append({
                        "type": "decision",
                        "text": match.group(0),
                        "confidence": 0.9,
                        "context": text[max(0, match.start()-40):match.end()+40].strip(),
                    })

            # Problem-aware signal: if item has both pain_points AND entity mentions
            pain_points = item.metadata.get("pain_points", [])
            entities = item.metadata.get("entities", {})
            if pain_points and (entities.get("companies") or entities.get("products")):
                signals.append({
                    "type": "problem_aware",
                    "text": f"Complaint about {', '.join((entities.get('companies') or entities.get('products', []))[:2])}",
                    "confidence": 0.5,
                    "context": pain_points[0].get("context", "")[:200],
                })

            # Deduplicate by type+text
            seen: set[str] = set()
            unique_signals = []
            for s in signals:
                key = f"{s['type']}:{s['text']}"
                if key not in seen:
                    seen.add(key)
                    unique_signals.append(s)

            # Sort by confidence (highest first)
            unique_signals.sort(key=lambda x: x["confidence"], reverse=True)

            if unique_signals:
                item.metadata["buying_signals"] = unique_signals
                # Assign overall buying_intent score
                max_confidence = max(s["confidence"] for s in unique_signals)
                signal_count = len(unique_signals)
                item.metadata["buying_intent"] = round(min(1.0, max_confidence * (1 + signal_count * 0.1)), 2)
                total_signals += len(unique_signals)
            else:
                item.metadata["buying_intent"] = 0.0

        self._logger.info(
            f"Buying signals: {total_signals} signals across {len(items)} items",
            extra={"total_signals": total_signals, "items": len(items)}
        )
        return items
