"""
Pain-point extraction — identifies complaints, frustrations, and unmet needs.

Deterministic approach using pattern matching:
1. Complaint patterns ("X is too expensive", "X doesn't work", "frustrated with")
2. Feature-request patterns ("wish X had", "need a tool that", "looking for")
3. Question patterns ("how do I", "any alternative to", "is there a way")

Output: item.metadata["pain_points"] = list of {type, text, severity}
"""
from __future__ import annotations

import re
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


# Pain-point patterns
COMPLAINT_PATTERNS = [
    (re.compile(r"\b(?:too\s+)?(?:expensive|pricey|costly|overpriced)\b", re.I), "pricing", "high"),
    (re.compile(r"\b(?:doesn'?t|does\s+not|didn'?t|did\s+not)\s+work\b", re.I), "functionality", "high"),
    (re.compile(r"\b(?:frustrat\w+|annoy\w+|irritat\w+)\b", re.I), "frustration", "medium"),
    (re.compile(r"\b(?:slow|laggy|sluggish|unresponsive)\b", re.I), "performance", "medium"),
    (re.compile(r"\b(?:confusing|complicated|hard\s+to\s+use|difficult)\b", re.I), "usability", "medium"),
    (re.compile(r"\b(?:broken|bug|crash|error|fail)\w*\b", re.I), "bug", "high"),
    (re.compile(r"\b(?:terrible|awful|worst|hate)\b", re.I), "dissatisfaction", "high"),
    (re.compile(r"\b(?:limit\w+|restrict\w+|can'?t\s+do)\b", re.I), "limitation", "medium"),
]

FEATURE_REQUEST_PATTERNS = [
    (re.compile(r"\bwish\s+(?:it|they|this)\s+(?:had|could|would)\b", re.I), "feature_wish"),
    (re.compile(r"\bneed\s+(?:a\s+)?(?:tool|app|platform|service)\s+that\b", re.I), "need_tool"),
    (re.compile(r"\blooking\s+for\s+(?:a\s+)?(?:tool|app|alternative)\b", re.I), "looking_for"),
    (re.compile(r"\bis\s+there\s+(?:a|an)\s+(?:tool|app|way)\b", re.I), "seeking"),
    (re.compile(r"\bany\s+(?:alternative|recommendation|suggestion)\b", re.I), "seeking_alternative"),
    (re.compile(r"\bshould\s+(?:have|include|support|offer)\b", re.I), "suggestion"),
]

QUESTION_PATTERNS = [
    (re.compile(r"\bhow\s+(?:do|can|to)\b", re.I), "how_to"),
    (re.compile(r"\bwhy\s+(?:is|does|can'?t)\b", re.I), "why"),
    (re.compile(r"\bwhat(?:'?s|s)\s+(?:the\s+)?best\b", re.I), "best_of"),
    (re.compile(r"\banyone\s+(?:using|tried|know)\b", re.I), "community_question"),
]


class PainPointExtractionProcessor(BaseProcessor):
    name = "pain_point_extraction"

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        total_pain_points = 0

        for item in items:
            text = f"{item.title} {item.body}"
            pain_points: list[dict] = []

            # Complaints
            for pattern, category, severity in COMPLAINT_PATTERNS:
                for match in pattern.finditer(text):
                    # Extract surrounding context (50 chars before/after)
                    start = max(0, match.start() - 50)
                    end = min(len(text), match.end() + 50)
                    context = text[start:end].strip()
                    pain_points.append({
                        "type": "complaint",
                        "category": category,
                        "severity": severity,
                        "text": match.group(0),
                        "context": context,
                    })

            # Feature requests
            for pattern, request_type in FEATURE_REQUEST_PATTERNS:
                for match in pattern.finditer(text):
                    start = max(0, match.start() - 30)
                    end = min(len(text), match.end() + 80)
                    context = text[start:end].strip()
                    pain_points.append({
                        "type": "feature_request",
                        "category": request_type,
                        "severity": "medium",
                        "text": match.group(0),
                        "context": context,
                    })

            # Questions (lower severity — informational)
            for pattern, question_type in QUESTION_PATTERNS:
                for match in pattern.finditer(text):
                    pain_points.append({
                        "type": "question",
                        "category": question_type,
                        "severity": "low",
                        "text": match.group(0),
                        "context": text[max(0, match.start()-30):match.end()+80].strip(),
                    })

            # Deduplicate by text
            seen: set[str] = set()
            unique_pp = []
            for pp in pain_points:
                key = pp["text"].lower()
                if key not in seen:
                    seen.add(key)
                    unique_pp.append(pp)

            if unique_pp:
                item.metadata["pain_points"] = unique_pp
                total_pain_points += len(unique_pp)

        self._logger.info(
            f"Pain-point extraction: {total_pain_points} pain points across {len(items)} items",
            extra={"total_pain_points": total_pain_points, "items": len(items)}
        )
        return items
