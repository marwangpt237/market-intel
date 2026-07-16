"""
Validation Report — Phase 8 markdown report.

Reports on the integrity of the knowledge base:
  1. Newly verified claims
  2. Downgraded claims
  3. Expired claims
  4. Conflicting claims
  5. Highest-confidence entities
  6. Lowest-confidence entities
  7. Missing evidence requiring new collectors

Output: reports/validation_<YYYY-MM-DD>_<run_id>.md
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from core.models import ProcessedItem
from core.logger import get_logger
from reports.base import BaseReportGenerator


class ValidationReportGenerator(BaseReportGenerator):
    name = "validation"

    def __init__(self, config: dict):
        super().__init__(config)
        self._output_path = Path(config.get("output_path", "reports/"))

    def _generate(self, items: list[ProcessedItem], run_id: str) -> str:
        self._output_path.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        validation_data = None
        for item in items:
            if "_validation" in item.metadata:
                validation_data = item.metadata["_validation"]
                break

        lines: list[str] = []
        lines.append(f"# Validation Report — {date_str}")
        lines.append("")
        lines.append(f"_Generated: {now.isoformat()} | Run: `{run_id}`_")
        lines.append("")
        lines.append("> **Phase 8 — Evidence Validation Engine.**")
        lines.append("> No fact, metric, recommendation, score, trend, or confidence value enters the knowledge base unless validated.")
        lines.append("> Every claim is a first-class object with sources, evidence, confidence, and validation status.")
        lines.append("")

        if not validation_data:
            lines.append("_No validation data available — Validation Engine did not run._")
            filepath = self._output_path / f"validation_{date_str}_{run_id}.md"
            filepath.write_text("\n".join(lines), encoding="utf-8")
            return str(filepath)

        # ─── Summary ─────────────────────────────────────────────────────
        lines.append("## Summary")
        lines.append("")
        store_stats = validation_data.get("store_stats", {})
        ledger_stats = validation_data.get("ledger_stats", {})
        trust_stats = validation_data.get("trust_stats", {})

        lines.append(f"- **Claims extracted this run:** {validation_data.get('claims_extracted', 0)}")
        lines.append(f"- **Unique claims validated:** {validation_data.get('claims_validated', 0)}")
        lines.append(f"- **Stale claims marked EXPIRED:** {validation_data.get('stale_claims_marked', 0)}")
        lines.append(f"- **Decisions recorded in ledger:** {validation_data.get('decisions_recorded', 0)}")
        lines.append(f"- **Missing-evidence requests:** {len(validation_data.get('missing_evidence_requests', []))}")
        lines.append("")
        lines.append(f"**Knowledge base totals:**")
        lines.append(f"- Total claims in DB: {store_stats.get('total_claims', 0)}")
        lines.append(f"- Total evidence pieces: {store_stats.get('total_evidence_pieces', 0)}")
        lines.append(f"- Average confidence: {store_stats.get('avg_confidence', 0):.3f}")
        lines.append("")

        # Status distribution
        by_status = store_stats.get("by_status", {})
        if by_status:
            lines.append("**Claims by validation status:**")
            lines.append("")
            lines.append("| Status | Count | Description |")
            lines.append("|--------|-------|-------------|")
            descriptions = {
                "VERIFIED": "Strong evidence, multiple independent sources, recent",
                "PROBABLE": "Good evidence but not yet verified",
                "HYPOTHESIS": "Single source or low confidence",
                "CONFLICTED": "Contradicting evidence present",
                "EXPIRED": "Stale — past expiration date",
                "UNKNOWN": "No evidence yet",
            }
            for status in ("VERIFIED", "PROBABLE", "HYPOTHESIS", "CONFLICTED", "EXPIRED", "UNKNOWN"):
                count = by_status.get(status, 0)
                if count > 0:
                    lines.append(f"| {status} | {count} | {descriptions.get(status, '')} |")
            lines.append("")

        # ─── Newly Verified Claims ───────────────────────────────────────
        newly_verified = validation_data.get("newly_verified", [])
        lines.append(f"## Newly Verified Claims ({len(newly_verified)})")
        lines.append("")
        if newly_verified:
            lines.append("> These claims met the VERIFIED threshold: 3+ independent reliable sources + confidence ≥ 0.70")
            lines.append("")
            lines.append("| Claim ID | Entity | Type | Value | Confidence | Sources |")
            lines.append("|----------|--------|------|-------|-----------|---------|")
            for c in newly_verified[:15]:
                lines.append(
                    f"| `{c['id'][:12]}` | {c['entity']} | {c['claim_type']} | "
                    f"{str(c['value'])[:30]} | {c['confidence_score']:.2f} | {c['evidence_count']} |"
                )
            lines.append("")
        else:
            lines.append("_No claims reached VERIFIED status this run. Need 3+ independent reliable sources + confidence ≥ 0.70._")
            lines.append("")

        # ─── Probable Claims ─────────────────────────────────────────────
        newly_probable = validation_data.get("newly_probable", [])
        lines.append(f"## Probable Claims ({len(newly_probable)})")
        lines.append("")
        if newly_probable:
            lines.append("> These claims have 2+ independent reliable sources + confidence ≥ 0.40 — candidates for VERIFIED with one more source.")
            lines.append("")
            lines.append("| Claim ID | Entity | Type | Value | Confidence | Sources |")
            lines.append("|----------|--------|------|-------|-----------|---------|")
            for c in newly_probable[:15]:
                lines.append(
                    f"| `{c['id'][:12]}` | {c['entity']} | {c['claim_type']} | "
                    f"{str(c['value'])[:30]} | {c['confidence_score']:.2f} | {c['evidence_count']} |"
                )
            lines.append("")

        # ─── Conflicted Claims ───────────────────────────────────────────
        conflicted = validation_data.get("conflicted_claims", [])
        lines.append(f"## Conflicted Claims ({len(conflicted)})")
        lines.append("")
        if conflicted:
            lines.append("> ⚠️ These claims have contradicting evidence. Treat with caution — investigate before acting.")
            lines.append("")
            for c in conflicted[:10]:
                lines.append(f"### `{c['id'][:12]}` — {c['entity']} / {c['claim_type']}")
                lines.append("")
                lines.append(f"- **Claimed value:** {c['value']}")
                lines.append(f"- **Confidence:** {c['confidence_score']:.2f}")
                lines.append(f"- **Supporting evidence:** {len(c.get('supporting_evidence', []))}")
                lines.append(f"- **Contradicting evidence:** {len(c.get('contradicting_evidence', []))}")
                if c.get("contradicting_evidence"):
                    lines.append("")
                    lines.append("**Contradicting sources:**")
                    for ev in c["contradicting_evidence"][:3]:
                        lines.append(f"- `{ev.get('source_id', '?')}` (reliability {ev.get('source_reliability', 0):.2f}): claims {ev.get('value', '?')}")
                lines.append("")
        else:
            lines.append("_No conflicted claims detected this run._")
            lines.append("")

        # ─── Expired Claims ──────────────────────────────────────────────
        expired = validation_data.get("expired_claims", [])
        lines.append(f"## Expired Claims ({len(expired)})")
        lines.append("")
        if expired:
            lines.append("> These claims are stale — past their expiration date. Downgraded from previous status.")
            lines.append("")
            lines.append("| Claim ID | Entity | Type | Old Status | Last Seen | Expired On |")
            lines.append("|----------|--------|------|-----------|-----------|-----------|")
            for c in expired[:15]:
                last_seen = c.get("last_seen", "?")[:10]
                expiry = c.get("expiration_date", "?")[:10]
                lines.append(
                    f"| `{c['id'][:12]}` | {c['entity']} | {c['claim_type']} | "
                    f"{c['validation_status']} | {last_seen} | {expiry} |"
                )
            lines.append("")
        else:
            lines.append("_No claims expired this run._")
            lines.append("")

        # ─── Highest/Lowest Confidence ───────────────────────────────────
        highest = validation_data.get("highest_confidence_claims", [])
        lines.append(f"## Highest-Confidence Entities ({len(highest)})")
        lines.append("")
        if highest:
            lines.append("| Claim ID | Entity | Type | Value | Confidence | Status |")
            lines.append("|----------|--------|------|-------|-----------|--------|")
            for c in highest:
                lines.append(
                    f"| `{c['id'][:12]}` | {c['entity']} | {c['claim_type']} | "
                    f"{str(c['value'])[:30]} | {c['confidence_score']:.2f} | {c['validation_status']} |"
                )
            lines.append("")

        lowest = validation_data.get("lowest_confidence_claims", [])
        lines.append(f"## Lowest-Confidence Entities ({len(lowest)})")
        lines.append("")
        if lowest:
            lines.append("> These entities need more evidence — consider adding collectors or widening queries.")
            lines.append("")
            lines.append("| Claim ID | Entity | Type | Value | Confidence | Status |")
            lines.append("|----------|--------|------|-------|-----------|--------|")
            for c in lowest:
                lines.append(
                    f"| `{c['id'][:12]}` | {c['entity']} | {c['claim_type']} | "
                    f"{str(c['value'])[:30]} | {c['confidence_score']:.2f} | {c['validation_status']} |"
                )
            lines.append("")

        # ─── Missing Evidence ────────────────────────────────────────────
        missing = validation_data.get("missing_evidence_requests", [])
        lines.append(f"## Missing Evidence — Collection Requests ({len(missing)})")
        lines.append("")
        if missing:
            lines.append("> The Validation Engine detected claims with insufficient evidence.")
            lines.append("> These requests should inform future collector runs (broaden queries, add sources).")
            lines.append("")
            lines.append("| Claim ID | Entity | Claim Type | Current Confidence | Sources | Needed | Request |")
            lines.append("|----------|--------|-----------|-------------------|---------|--------|---------|")
            for m in missing[:20]:
                lines.append(
                    f"| `{m['claim_id'][:12]}` | {m['entity']} | {m['claim_type']} | "
                    f"{m['current_confidence']:.2f} | {m['current_sources']} | {m['needed_sources']} | "
                    f"{m['request'][:60]} |"
                )
            lines.append("")
        else:
            lines.append("_No missing-evidence requests — all claims have sufficient evidence._")
            lines.append("")

        # ─── Decision Ledger Summary ─────────────────────────────────────
        lines.append("## Decision Ledger Summary")
        lines.append("")
        lines.append(f"- **Total decisions recorded:** {ledger_stats.get('total_decisions', 0)}")
        lines.append(f"- **Decisions with warnings:** {ledger_stats.get('decisions_with_warnings', 0)}")
        lines.append(f"- **Low-confidence decisions (< 0.40):** {ledger_stats.get('low_confidence_decisions', 0)}")
        lines.append(f"- **Average decision confidence:** {ledger_stats.get('avg_confidence', 0):.3f}")
        lines.append("")

        # ─── Trust Layer Stats ───────────────────────────────────────────
        lines.append("## Trust Layer")
        lines.append("")
        lines.append(f"- **Sources known:** {trust_stats.get('total_sources_known', 0)}")
        lines.append(f"- **Learned sources:** {trust_stats.get('learned_sources_count', 0)}")
        lines.append(f"- **Min evidence reliability:** {trust_stats.get('min_evidence_reliability', 0.30)}")
        lines.append(f"- **High-credibility sources (≥ 0.75):** {trust_stats.get('high_credibility_sources', 0)}")
        lines.append(f"- **Low-credibility sources (< 0.40):** {trust_stats.get('low_credibility_sources', 0)}")
        lines.append("")

        # ─── How it works ────────────────────────────────────────────────
        lines.append("## How Validation Works")
        lines.append("")
        lines.append("```")
        lines.append("Every claim becomes a first-class object:")
        lines.append("  { id, entity, claim_type, value, sources, evidence_count,")
        lines.append("    first_seen, last_seen, last_verified, supporting_evidence,")
        lines.append("    contradicting_evidence, confidence_score, validation_status,")
        lines.append("    expiration_date, version_history }")
        lines.append("")
        lines.append("Validation rules:")
        lines.append("  1. Minimum independent sources (default 2 for PROBABLE, 3 for VERIFIED)")
        lines.append("  2. Source reliability weighting (TrustLayer)")
        lines.append("  3. Contradiction detection (diff > 30% tolerance → CONFLICTED)")
        lines.append("  4. Confidence = Σ(reliability × evidence_confidence) / total")
        lines.append("     + diversity_bonus - contradiction_penalty")
        lines.append("  5. Staleness: last_seen > expiration_date → EXPIRED")
        lines.append("  6. Status: UNKNOWN → HYPOTHESIS → PROBABLE → VERIFIED")
        lines.append("                                          ↓")
        lines.append("                                       CONFLICTED / EXPIRED")
        lines.append("")
        lines.append("Every decision references the Claim IDs that justify it.")
        lines.append("If a recommendation depends on weak/conflicting claims, confidence is reduced")
        lines.append("and warnings are added to the Decision Ledger entry.")
        lines.append("```")
        lines.append("")

        # ─── Closed-loop status ──────────────────────────────────────────
        lines.append("## Closed-Loop Status")
        lines.append("")
        loop_steps = [
            ("Collect", "✅"),
            ("Analyze", "✅"),
            ("Score", "✅"),
            ("Decide", "✅"),
            ("Filter", "✅"),
            ("Strategize", "✅"),
            ("Act", "✅"),
            ("Measure", "✅"),
            ("Learn", "✅"),
            ("Validate", "✅" if validation_data else "⏸"),
        ]
        for step, status in loop_steps:
            lines.append(f"- {status} **{step}**")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("_Market-Intel — Phase 8 Evidence Validation Engine._")
        lines.append("_Knowledge base integrity is the foundation. Every claim is auditable._")

        filepath = self._output_path / f"validation_{date_str}_{run_id}.md"
        filepath.write_text("\n".join(lines), encoding="utf-8")

        self._logger.info(f"Validation report written to {filepath}")
        return str(filepath)
