"""
Strategy Engine — Phase 5 architectural addition.

Takes the filtered decisions and produces an OPTIMAL PLAN under
limited resources (budget USD + time hours).

Pipeline:
  Decisions (filtered) → Cost estimation → ROI estimation →
  Multi-dimensional knapsack → Optimal plan + projected outcomes

Cost model per decision type (USD + hours):
  build_feature    → $5k-50k, 80-200h
  launch_campaign  → $500-5k, 10-20h
  write_content    → $100-500, 4-8h
  reach_out        → $0-100, 2-5h
  monitor_competitor → $0, 1-2h (ongoing weekly)
  investigate      → $0-200, 2-4h

ROI estimation (0-100):
  Combines opportunity_score, trend_score, expected_impact multiplier,
  historical performance (from Learning Engine outcomes), urgency bonus,
  and divides by cost_factor (relative to budget+time).

Knapsack:
  Greedy multi-dimensional — sort by ROI / cost_factor, fill until
  budget OR time runs out. Deterministic, fast, no ML.

Output (stored on items[0].metadata["_strategy"]):
  - selected: list of decisions in the optimal plan (ordered)
  - excluded: list of decisions that didn't fit (with reason)
  - projected: total projected signups, conversions, revenue, ROI
  - utilization: budget_used, time_used, % of each
  - constraints: budget_usd, time_hours
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


# Cost ranges per decision type (USD + hours)
# These are estimates for a solo founder / small team
COST_MODEL: dict[str, dict[str, tuple[int, int]]] = {
    "build_feature":      {"usd": (5000, 50000),  "hours": (80, 200)},
    "launch_campaign":    {"usd": (500, 5000),    "hours": (10, 20)},
    "write_content":      {"usd": (100, 500),     "hours": (4, 8)},
    "reach_out":          {"usd": (0, 100),       "hours": (2, 5)},
    "monitor_competitor": {"usd": (0, 0),         "hours": (1, 2)},
    "investigate":        {"usd": (0, 200),       "hours": (2, 4)},
}

# Strategic value multiplier per decision type
TYPE_VALUE_MULTIPLIER = {
    "build_feature":      3.0,   # high value if successful (asset)
    "launch_campaign":    1.5,   # medium (acquisition)
    "write_content":      1.0,   # baseline (asset + traffic)
    "reach_out":          2.0,   # direct conversion potential
    "monitor_competitor": 0.3,   # informational
    "investigate":        0.5,   # optionality
}

# Impact weights
IMPACT_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.3}

# Priority weights
PRIORITY_WEIGHT = {"P0": 1.3, "P1": 1.0, "P2": 0.7, "P3": 0.4}

# Default outcome projections per decision type (used when no historical data)
DEFAULT_PROJECTIONS = {
    "build_feature":      {"signups": 50,  "conversions": 5,   "revenue": 500},
    "launch_campaign":    {"signups": 30,  "conversions": 3,   "revenue": 300},
    "write_content":      {"signups": 15,  "conversions": 1,   "revenue": 100},
    "reach_out":          {"signups": 10,  "conversions": 2,   "revenue": 200},
    "monitor_competitor": {"signups": 0,   "conversions": 0,   "revenue": 0},
    "investigate":        {"signups": 0,   "conversions": 0,   "revenue": 0},
}


class StrategyEngine(BaseProcessor):
    name = "strategy_engine"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._budget_usd: int = int(self._config.get("budget_usd", 500))
        self._time_hours: int = int(self._config.get("time_hours", 20))
        self._team_size: int = int(self._config.get("team_size", 1))
        # Historical performance data (from Learning Engine, optional)
        self._historical: dict[str, dict] = self._config.get("historical_performance", {})

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        if not items:
            return items

        # Find decisions (already filtered by FalsePositiveFilter)
        decisions_data = None
        for item in items:
            if "_decisions" in item.metadata:
                decisions_data = item.metadata["_decisions"]
                break

        if not decisions_data:
            self._logger.info("No decisions — skipping strategy engine")
            return items

        decisions = decisions_data.get("decisions", [])
        if not decisions:
            self._logger.info("Empty decisions list — skipping strategy engine")
            return items

        # 1. Estimate cost + ROI for each decision
        scored: list[dict] = []
        for d in decisions:
            cost = self._estimate_cost(d)
            roi = self._estimate_roi(d, cost)
            scored.append({
                "decision": d,
                "cost_usd": cost["usd"],
                "cost_hours": cost["hours"],
                "roi": roi,
                "roi_per_dollar": roi / max(1, cost["usd"]),
                "roi_per_hour": roi / max(1, cost["hours"]),
            })

        # 2. Greedy knapsack: sort by ROI / combined resource cost
        # Combined cost factor: how much of the budget+time this consumes
        for s in scored:
            budget_fraction = s["cost_usd"] / max(1, self._budget_usd)
            time_fraction = s["cost_hours"] / max(1, self._time_hours * self._team_size)
            # Max of fractions — the binding constraint
            s["binding_fraction"] = max(budget_fraction, time_fraction)
            # ROI per resource unit (higher = more efficient)
            s["efficiency"] = s["roi"] / max(0.01, s["binding_fraction"])

        # Sort by efficiency desc (best bang-for-buck first)
        scored.sort(key=lambda s: s["efficiency"], reverse=True)

        # 3. Greedy fill under constraints
        selected: list[dict] = []
        excluded: list[dict] = []
        budget_used = 0
        time_used = 0

        for s in scored:
            d = s["decision"]
            usd = s["cost_usd"]
            hrs = s["cost_hours"]

            # Check if it fits
            if budget_used + usd <= self._budget_usd and time_used + hrs <= self._time_hours * self._team_size:
                selected.append({
                    "decision": d,
                    "cost_usd": usd,
                    "cost_hours": hrs,
                    "roi": s["roi"],
                    "efficiency": round(s["efficiency"], 2),
                    "cumulative_budget": budget_used + usd,
                    "cumulative_hours": time_used + hrs,
                    "projected_signups": self._project_signups(d),
                    "projected_conversions": self._project_conversions(d),
                    "projected_revenue": self._project_revenue(d),
                })
                budget_used += usd
                time_used += hrs
            else:
                # Why didn't it fit?
                if budget_used + usd > self._budget_usd:
                    reason = f"over_budget (${usd} would exceed ${self._budget_usd} budget)"
                else:
                    reason = f"over_time ({hrs}h would exceed {self._time_hours * self._team_size}h available)"
                excluded.append({
                    "decision": d,
                    "cost_usd": usd,
                    "cost_hours": hrs,
                    "roi": s["roi"],
                    "reason": reason,
                })

        # 4. Compute projected totals
        total_signups = sum(s["projected_signups"] for s in selected)
        total_conversions = sum(s["projected_conversions"] for s in selected)
        total_revenue = sum(s["projected_revenue"] for s in selected)
        total_roi = sum(s["roi"] for s in selected)

        # 5. Stash strategy on first item
        items[0].metadata["_strategy"] = {
            "constraints": {
                "budget_usd": self._budget_usd,
                "time_hours": self._time_hours,
                "team_size": self._team_size,
                "total_budget_usd": self._budget_usd,
                "total_time_hours": self._time_hours * self._team_size,
            },
            "selected": selected,
            "excluded": excluded,
            "projected": {
                "total_signups": total_signups,
                "total_conversions": total_conversions,
                "total_revenue_usd": total_revenue,
                "total_roi": round(total_roi, 1),
                "avg_roi_per_selected": round(total_roi / max(1, len(selected)), 1),
            },
            "utilization": {
                "budget_used_usd": budget_used,
                "budget_used_pct": round(budget_used / max(1, self._budget_usd) * 100, 1),
                "time_used_hours": time_used,
                "time_used_pct": round(time_used / max(1, self._time_hours * self._team_size) * 100, 1),
                "actions_selected": len(selected),
                "actions_excluded": len(excluded),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        self._logger.info(
            f"Strategy engine: {len(selected)}/{len(scored)} actions selected, "
            f"${budget_used}/${self._budget_usd} budget, {time_used}/{self._time_hours * self._team_size}h, "
            f"projected ROI={total_roi:.1f}, signups={total_signups}, revenue=${total_revenue}",
            extra=items[0].metadata["_strategy"]["utilization"],
        )
        return items

    # ─── Cost estimation ─────────────────────────────────────────────────

    def _estimate_cost(self, decision: dict) -> dict[str, int]:
        """Estimate USD + hours cost for a decision."""
        dtype = decision.get("type", "investigate")
        model = COST_MODEL.get(dtype, COST_MODEL["investigate"])
        usd_range = model["usd"]
        hours_range = model["hours"]

        # Adjust within range based on expected_impact (high → upper bound)
        impact = decision.get("expected_impact", "medium")
        impact_factor = {"high": 0.9, "medium": 0.5, "low": 0.25}[impact]

        usd = int(usd_range[0] + (usd_range[1] - usd_range[0]) * impact_factor)
        hours = int(hours_range[0] + (hours_range[1] - hours_range[0]) * impact_factor)

        # Round to nice numbers
        if usd > 1000:
            usd = round(usd / 100) * 100
        elif usd > 100:
            usd = round(usd / 10) * 10

        return {"usd": usd, "hours": hours}

    # ─── ROI estimation ──────────────────────────────────────────────────

    def _estimate_roi(self, decision: dict, cost: dict) -> float:
        """Estimate ROI on a 0-100 scale.

        ROI = (opportunity + trend + impact + urgency + historical) / cost_factor

        Higher opportunity + trend + impact → higher numerator
        Higher cost relative to budget+time → higher cost_factor → lower ROI
        """
        target = decision.get("target", "")
        dtype = decision.get("type", "investigate")
        priority = decision.get("priority", "P3")
        impact = decision.get("expected_impact", "low")

        # Pull opportunity_score from decision rationale (parsed) or default
        opportunity_score = self._extract_opportunity_from_rationale(decision.get("rationale", ""))
        trend_score = self._extract_trend_from_rationale(decision.get("rationale", ""))

        # Multiplier
        type_mult = TYPE_VALUE_MULTIPLIER.get(dtype, 0.5)
        impact_mult = IMPACT_WEIGHT.get(impact, 0.3)
        priority_mult = PRIORITY_WEIGHT.get(priority, 0.4)

        # Historical performance adjustment (if Learning Engine has data)
        historical_bonus = self._get_historical_bonus(dtype, priority)

        # Urgency bonus
        urgency_bonus = 0
        if decision.get("urgency_hours"):
            # More urgent = higher bonus (capped at 15)
            urgency_bonus = max(0, 15 - decision["urgency_hours"] / 24)

        # Numerator (raw value)
        numerator = (
            opportunity_score * 0.40
            + trend_score * 0.20
            + type_mult * 15  # scale type_mult to 0-45 range
            + impact_mult * 10
            + priority_mult * 5
            + urgency_bonus
            + historical_bonus
        )

        # Cost factor: how much of the budget+time this consumes
        budget_fraction = cost["usd"] / max(1, self._budget_usd)
        time_fraction = cost["hours"] / max(1, self._time_hours * self._team_size)
        # Use sqrt of binding fraction to be gentler on cheap items
        binding = max(budget_fraction, time_fraction)
        cost_factor = 1.0 + math.sqrt(binding)

        roi = numerator / cost_factor
        return round(max(0, min(100, roi)), 1)

    @staticmethod
    def _extract_opportunity_from_rationale(rationale: str) -> float:
        """Extract opportunity score from decision rationale text.

        Looks for patterns like 'opportunity=75/100' or 'opportunity score: 75'.
        """
        import re
        if not rationale:
            return 30.0  # default
        # Match "opportunity=N/100" or "opportunity=N" or "opportunity score: N"
        m = re.search(r"opportunity[^0-9]*(\d+)", rationale, re.IGNORECASE)
        if m:
            return float(m.group(1))
        return 30.0

    @staticmethod
    def _extract_trend_from_rationale(rationale: str) -> float:
        """Extract trend score from rationale text."""
        import re
        if not rationale:
            return 20.0
        m = re.search(r"trend[^0-9]*(\d+)", rationale, re.IGNORECASE)
        if m:
            return float(m.group(1))
        # If rationale mentions 'hot' or 'rising', give it 60
        if "hot" in rationale.lower() or "rising" in rationale.lower():
            return 60.0
        return 20.0

    def _get_historical_bonus(self, dtype: str, priority: str) -> float:
        """Look up historical performance for this (type, priority) bucket.

        Returns a bonus 0-15 based on how this bucket has performed in past.
        """
        key = f"{dtype}_{priority}"
        bucket = self._historical.get(key)
        if not bucket:
            return 0.0
        avg_outcome = bucket.get("avg_outcome", 0)
        baseline = bucket.get("baseline_outcome", 0)
        if baseline == 0:
            return 0.0
        delta = (avg_outcome - baseline) / baseline
        # +50% performance → +7.5 bonus, capped at 15
        return max(0, min(15, delta * 15))

    # ─── Outcome projection ─────────────────────────────────────────────

    def _project_signups(self, decision: dict) -> int:
        dtype = decision.get("type", "investigate")
        base = DEFAULT_PROJECTIONS.get(dtype, {}).get("signups", 0)
        # Scale by opportunity (parsed from rationale)
        opp = self._extract_opportunity_from_rationale(decision.get("rationale", ""))
        return int(base * (0.5 + opp / 100))

    def _project_conversions(self, decision: dict) -> int:
        dtype = decision.get("type", "investigate")
        base = DEFAULT_PROJECTIONS.get(dtype, {}).get("conversions", 0)
        opp = self._extract_opportunity_from_rationale(decision.get("rationale", ""))
        return int(base * (0.5 + opp / 100))

    def _project_revenue(self, decision: dict) -> int:
        dtype = decision.get("type", "investigate")
        base = DEFAULT_PROJECTIONS.get(dtype, {}).get("revenue", 0)
        opp = self._extract_opportunity_from_rationale(decision.get("rationale", ""))
        return int(base * (0.5 + opp / 100))
