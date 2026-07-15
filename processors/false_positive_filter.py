"""
False Positive Filter — Phase 5 data-quality module.

Runs AFTER the Decision Engine. Removes decisions that are technically
correct but strategically useless:

  1. Mega-corp targets — "Build Google alternative" is not a realistic
     startup strategy. Skip decisions targeting trillion-dollar companies
     unless explicitly allowlisted.
  2. Generic-term targets — decisions targeting words like "marketing",
     "seo", "analytics" (these are categories, not competitors).
  3. Weak evidence — decisions backed by < N items or single-source
     evidence.
  4. Low authority — decisions where all evidence items have low
     authority_score (set by SourceAuthorityProcessor).
  5. Duplicate target — if 3+ decisions target the same entity, keep
     only the highest-ROI one.
  6. Non-English target — decisions where the target name contains
     non-ASCII chars or foreign words.

Each filtered decision is logged with the filter reason, so the
Decision Report can show "filtered: 4 (mega_corp: 2, weak_evidence: 1,
duplicate: 1)" for transparency.
"""
from __future__ import annotations

from collections import defaultdict
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


# Trillion-dollar / mega-cap companies — don't try to "launch an alternative"
# Allowlist exceptions: companies that ARE realistic startup targets (smaller SaaS)
MEGA_CORP_BLOCKLIST = {
    # Big tech
    "google", "microsoft", "apple", "amazon", "meta", "facebook", "instagram",
    "twitter", "x", "linkedin", "tiktok", "youtube", "netflix", "spotify",
    "reddit", "discord", "telegram", "whatsapp", "snapchat", "pinterest",
    # Cloud / infra
    "aws", "azure", "google cloud", "oracle", "ibm", "sap", "salesforce",
    "adobe", "intel", "nvidia", "amd", "cloudflare",
    # Platforms (not realistic to "replace")
    "wordpress", "shopify", "wix", "squarespace", "godaddy",
    # AI labs (frontier — can't compete head-on)
    "openai", "anthropic", "midjourney", "stability", "google deepmind",
}

# Generic terms that shouldn't be decision targets
GENERIC_TERMS = {
    "marketing", "seo", "ppc", "analytics", "growth", "saas", "startup",
    "content", "email", "social media", "digital marketing", "advertising",
    "automation", "ai", "ml", "machine learning", "data", "cloud",
    "mobile", "web", "design", "branding", "copywriting", "crm", "cms",
    "erp", "hr", "finance", "operations", "sales", "support", "product",
    "engineering", "developer", "engineer", "manager", "team", "company",
    "tools", "platform", "software", "application", "service", "feature",
    "user", "customer", "client", "business", "market", "industry",
}

# Decision types where mega-corp filter applies
_ALTERNATIVE_DECISION_TYPES = {"build_feature", "launch_campaign", "reach_out"}


class FalsePositiveFilter(BaseProcessor):
    name = "false_positive_filter"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._min_evidence_count: int = self._config.get("min_evidence_count", 2)
        self._min_authority_avg: int = self._config.get("min_authority_avg", 40)
        self._mega_corp_blocklist: set[str] = set(self._config.get("mega_corp_blocklist", [])) | MEGA_CORP_BLOCKLIST
        self._generic_terms: set[str] = set(self._config.get("generic_terms", [])) | GENERIC_TERMS
        self._allowlist: set[str] = set(self._config.get("allowlist", []))
        # Default allowlist: smaller SaaS that ARE realistic targets
        self._allowlist |= {
            "hubspot", "mailchimp", "semrush", "ahrefs", "moz", "canva",
            "figma", "notion", "slack", "zoom", "stripe", "mailgun", "twilio",
            "maltego", "spiderfoot", "shodan", "virustotal", "hunter",
        }

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        if not items:
            return items

        # Find the item carrying decisions
        decisions_data = None
        for item in items:
            if "_decisions" in item.metadata:
                decisions_data = item.metadata["_decisions"]
                break

        if not decisions_data:
            self._logger.info("No decisions to filter — skipping false positive filter")
            return items

        decisions = decisions_data.get("decisions", [])
        kept: list[dict] = []
        filtered: list[dict] = []
        filter_counts: dict[str, int] = defaultdict(int)

        # Track targets for duplicate detection
        seen_targets: dict[str, dict] = {}  # target → best decision so far

        # First pass: filter by content rules
        for decision in decisions:
            reason = self._get_filter_reason(decision, items)
            if reason:
                decision_copy = dict(decision)
                decision_copy["filter_reason"] = reason
                filtered.append(decision_copy)
                filter_counts[reason] += 1
            else:
                kept.append(decision)

        # Second pass: dedupe by target — keep highest priority / highest impact
        unique_kept: list[dict] = []
        for decision in kept:
            target = decision.get("target", "").lower()
            if not target:
                unique_kept.append(decision)
                continue

            if target in seen_targets:
                existing = seen_targets[target]
                # Compare: higher priority wins; if tie, higher expected impact
                priority_weight = {"P0": 4, "P1": 3, "P2": 2, "P3": 1}
                impact_weight = {"high": 3, "medium": 2, "low": 1}
                new_score = priority_weight.get(decision.get("priority", "P3"), 1) * 10 + impact_weight.get(decision.get("expected_impact", "low"), 1)
                old_score = priority_weight.get(existing.get("priority", "P3"), 1) * 10 + impact_weight.get(existing.get("expected_impact", "low"), 1)
                if new_score > old_score:
                    # Replace existing with new
                    unique_kept = [d for d in unique_kept if d is not existing]
                    unique_kept.append(decision)
                    seen_targets[target] = decision
                    # Mark old as filtered
                    existing_copy = dict(existing)
                    existing_copy["filter_reason"] = "duplicate_target"
                    filtered.append(existing_copy)
                    filter_counts["duplicate_target"] += 1
                else:
                    # New is weaker — filter it
                    decision_copy = dict(decision)
                    decision_copy["filter_reason"] = "duplicate_target"
                    filtered.append(decision_copy)
                    filter_counts["duplicate_target"] += 1
            else:
                seen_targets[target] = decision
                unique_kept.append(decision)

        # Sort kept by priority (same as decision engine)
        priority_weight = {"P0": 4, "P1": 3, "P2": 2, "P3": 1}
        impact_weight = {"high": 3, "medium": 2, "low": 1}
        unique_kept.sort(
            key=lambda d: (priority_weight.get(d.get("priority", "P3"), 1), impact_weight.get(d.get("expected_impact", "low"), 1)),
            reverse=True,
        )

        # Update decisions_data in place
        decisions_data["decisions"] = unique_kept
        decisions_data["total"] = len(unique_kept)
        decisions_data["filtered"] = filtered
        decisions_data["filter_counts"] = dict(filter_counts)
        decisions_data["by_priority"] = {
            p: len([d for d in unique_kept if d.get("priority") == p])
            for p in ("P0", "P1", "P2", "P3")
        }
        decisions_data["by_type"] = self._count_by_type(unique_kept)

        self._logger.info(
            f"False positive filter: {len(unique_kept)} kept, {len(filtered)} filtered",
            extra={
                "kept": len(unique_kept),
                "filtered": len(filtered),
                "filter_counts": dict(filter_counts),
            },
        )
        return items

    def _get_filter_reason(self, decision: dict, items: list[ProcessedItem]) -> str | None:
        """Return filter reason if decision should be dropped, else None."""
        target = (decision.get("target", "") or "").lower().strip()
        dtype = decision.get("type", "")
        evidence = decision.get("evidence", [])

        # Rule 1: Mega-corp blocklist (only for alternative-type decisions)
        if dtype in _ALTERNATIVE_DECISION_TYPES and target in self._mega_corp_blocklist:
            if target not in self._allowlist:
                return "mega_corp"

        # Rule 2: Generic term
        if target in self._generic_terms:
            return "generic_term"

        # Rule 3: Non-ASCII / non-English target
        if target and any(ord(c) > 127 for c in target):
            return "non_english_target"

        # Rule 4: Weak evidence — too few items backing it
        if dtype != "monitor_competitor" and len(evidence) < self._min_evidence_count:
            return "weak_evidence"

        # Rule 5: Single-source evidence — all evidence from same source
        if dtype != "monitor_competitor" and evidence:
            sources = {e.get("source", "") for e in evidence}
            if len(sources) < 2 and len(evidence) < 3:
                return "single_source"

        # Rule 6: Low average authority — evidence items are all low-quality
        if evidence:
            authority_scores = []
            for e in evidence:
                # Find matching item in items list
                for item in items:
                    if item.id == e.get("item_id"):
                        authority_scores.append(item.metadata.get("authority_score", 50))
                        break
            if authority_scores:
                avg_auth = sum(authority_scores) / len(authority_scores)
                if avg_auth < self._min_authority_avg:
                    return "low_authority"

        # Rule 7: Very short target (< 3 chars) — usually extraction noise
        if len(target) < 3:
            return "short_target"

        return None

    @staticmethod
    def _count_by_type(decisions: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in decisions:
            t = d.get("type", "")
            counts[t] = counts.get(t, 0) + 1
        return counts
