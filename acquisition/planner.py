"""
Data Acquisition Planner — turns knowledge gaps into concrete collection plans.

For each KnowledgeGap, generates a CollectionPlan with:
  - plan_id
  - gap_id (reference to the gap being addressed)
  - target_entity
  - actions: list of concrete collection actions
      {
        "action_type": "crawl" | "increase_frequency" | "historical_collection" | "search_corroboration" | "schedule_validation",
        "source_type": "facebook_groups" | "ouedkniss" | "rss" | "reddit" | etc.,
        "query": str,
        "quantity": int,              # how many items to collect
        "frequency_hours": int,       # how often to collect
        "historical_days": int,       # for historical collection
        "next_validation_hours": int, # when to re-validate
      }
  - estimated_evidence_gain (how many new evidence pieces expected)
  - estimated_confidence_lift (how much confidence will improve)
  - total_cost (resource cost: API calls, time)
  - priority

The planner prioritizes actions that:
  1. Address P0 gaps first
  2. Maximize confidence lift per unit cost
  3. Use existing collectors when possible (no new infrastructure)
  4. Schedule re-validation to close the loop
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any
from core.logger import get_logger
from acquisition.knowledge_gap_detector import KnowledgeGap


# Source type → default quantity + frequency
_SOURCE_DEFAULTS: dict[str, dict] = {
    "facebook_groups": {
        "default_quantity": 20,
        "default_frequency_hours": 12,
        "cost_per_item": 0.5,        # arbitrary cost units (API calls / time)
        "evidence_yield_per_item": 0.8,  # expected evidence pieces per item collected
    },
    "facebook_marketplace": {
        "default_quantity": 15,
        "default_frequency_hours": 12,
        "cost_per_item": 0.6,
        "evidence_yield_per_item": 0.9,
    },
    "ouedkniss": {
        "default_quantity": 25,
        "default_frequency_hours": 6,
        "cost_per_item": 0.3,
        "evidence_yield_per_item": 0.85,
    },
    "reddit": {
        "default_quantity": 30,
        "default_frequency_hours": 6,
        "cost_per_item": 0.1,
        "evidence_yield_per_item": 0.6,
    },
    "hacker_news": {
        "default_quantity": 20,
        "default_frequency_hours": 6,
        "cost_per_item": 0.1,
        "evidence_yield_per_item": 0.5,
    },
    "rss": {
        "default_quantity": 50,
        "default_frequency_hours": 6,
        "cost_per_item": 0.05,
        "evidence_yield_per_item": 0.4,
    },
    "google_news": {
        "default_quantity": 30,
        "default_frequency_hours": 12,
        "cost_per_item": 0.1,
        "evidence_yield_per_item": 0.5,
    },
    "job_boards": {
        "default_quantity": 20,
        "default_frequency_hours": 12,
        "cost_per_item": 0.1,
        "evidence_yield_per_item": 0.6,
    },
}


@dataclass
class CollectionAction:
    """A single collection action in a plan."""
    action_type: str             # crawl | increase_frequency | historical_collection | search_corroboration | schedule_validation
    source_type: str
    query: str
    quantity: int
    frequency_hours: int = 0     # 0 = one-shot
    historical_days: int = 0     # 0 = current only
    next_validation_hours: int = 24
    estimated_evidence: int = 0
    estimated_cost: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CollectionPlan:
    """A plan to address a single knowledge gap."""
    plan_id: str
    gap_id: str
    target_entity: str
    entity_name: str
    gap_type: str
    priority: str
    current_confidence: float
    target_confidence: float
    actions: list[dict] = field(default_factory=list)
    estimated_evidence_gain: int = 0
    estimated_confidence_lift: float = 0.0
    total_cost: float = 0.0
    next_validation_hours: int = 24
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


class DataAcquisitionPlanner:
    """Plans data acquisition to fill knowledge gaps.

    For each gap, generates concrete actions like:
      - "Crawl 42 additional Facebook groups"
      - "Increase Ouedkniss collection to every 6 hours"
      - "Collect 30 days of historical prices"
      - "Search Reddit + Google News for corroboration"
      - "Schedule validation cycle in 24 hours"
    """

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._logger = get_logger("data_acquisition_planner")

        # Max actions per plan (to avoid runaway)
        self._max_actions_per_plan: int = int(self._config.get("max_actions_per_plan", 5))
        # Max total plans per run
        self._max_plans_per_run: int = int(self._config.get("max_plans_per_run", 20))

    def plan_for_gaps(self, gaps: list[KnowledgeGap]) -> list[CollectionPlan]:
        """Generate collection plans for a list of knowledge gaps.

        Args:
            gaps: list of KnowledgeGap objects, sorted by priority

        Returns:
            List of CollectionPlan objects, sorted by priority
        """
        if not gaps:
            return []

        plans: list[CollectionPlan] = []
        for gap in gaps[: self._max_plans_per_run]:
            plan = self._plan_for_gap(gap)
            if plan:
                plans.append(plan)

        self._logger.info(
            f"Data acquisition planner: {len(plans)} plans generated "
            f"for {len(gaps)} gaps, total estimated evidence: {sum(p.estimated_evidence_gain for p in plans)}, "
            f"total cost: {sum(p.total_cost for p in plans):.1f}"
        )
        return plans

    def _plan_for_gap(self, gap: KnowledgeGap) -> CollectionPlan | None:
        """Generate a collection plan for a single gap."""
        # Skip gaps with no suggested source types (internal claims)
        if not gap.suggested_source_types:
            # Still schedule a re-validation
            return self._build_minimal_plan(gap)

        actions: list[CollectionAction] = []

        # Action 1: Crawl primary source type with suggested queries
        primary_source = gap.suggested_source_types[0]
        for query in gap.suggested_queries[:2]:  # top 2 queries
            action = self._build_crawl_action(
                source_type=primary_source,
                query=query,
                gap=gap,
            )
            if action:
                actions.append(action)

        # Action 2: If multiple source types suggested, add corroboration search
        if len(gap.suggested_source_types) > 1:
            corroboration_source = gap.suggested_source_types[1]
            if gap.suggested_queries:
                action = self._build_corroboration_action(
                    source_type=corroboration_source,
                    query=gap.suggested_queries[0],
                    gap=gap,
                )
                if action:
                    actions.append(action)

        # Action 3: For price/demand gaps, add historical collection
        if gap.gap_type in ("average_price", "price_range", "demand_level", "stock_status"):
            action = self._build_historical_action(gap)
            if action:
                actions.append(action)

        # Action 4: For high-priority gaps, increase collection frequency
        if gap.priority in ("P0", "P1") and gap.suggested_source_types:
            action = self._build_frequency_action(gap)
            if action:
                actions.append(action)

        # Action 5: Always schedule re-validation
        validation_action = self._build_validation_action(gap)
        actions.append(validation_action)

        # Cap at max actions
        actions = actions[: self._max_actions_per_plan]

        # Compute totals
        total_evidence = sum(a.estimated_evidence for a in actions)
        total_cost = sum(a.estimated_cost for a in actions)

        # Estimate confidence lift
        # Heuristic: each 3 evidence pieces → +0.10 confidence
        confidence_lift = min(0.40, total_evidence / 3 * 0.10)

        # Build plan ID
        import hashlib
        plan_id = "plan_" + hashlib.sha1(f"{gap.gap_id}|{gap.priority}".encode()).hexdigest()[:12]

        return CollectionPlan(
            plan_id=plan_id,
            gap_id=gap.gap_id,
            target_entity=gap.entity,
            entity_name=gap.entity_name,
            gap_type=gap.gap_type,
            priority=gap.priority,
            current_confidence=gap.current_confidence,
            target_confidence=gap.target_confidence,
            actions=[a.to_dict() for a in actions],
            estimated_evidence_gain=total_evidence,
            estimated_confidence_lift=round(confidence_lift, 3),
            total_cost=round(total_cost, 2),
            next_validation_hours=gap.collection_urgency_hours,
        )

    def _build_crawl_action(
        self,
        source_type: str,
        query: str,
        gap: KnowledgeGap,
    ) -> CollectionAction | None:
        """Build a crawl action for a source + query."""
        defaults = _SOURCE_DEFAULTS.get(source_type, {"default_quantity": 20, "cost_per_item": 0.2, "evidence_yield_per_item": 0.5})
        quantity = defaults["default_quantity"]
        cost = quantity * defaults["cost_per_item"]
        evidence = int(quantity * defaults["evidence_yield_per_item"])

        return CollectionAction(
            action_type="crawl",
            source_type=source_type,
            query=query,
            quantity=quantity,
            frequency_hours=0,
            estimated_evidence=evidence,
            estimated_cost=cost,
        )

    def _build_corroboration_action(
        self,
        source_type: str,
        query: str,
        gap: KnowledgeGap,
    ) -> CollectionAction | None:
        """Build a corroboration search action."""
        defaults = _SOURCE_DEFAULTS.get(source_type, {"default_quantity": 15, "cost_per_item": 0.15, "evidence_yield_per_item": 0.4})
        quantity = defaults["default_quantity"]
        cost = quantity * defaults["cost_per_item"]
        evidence = int(quantity * defaults["evidence_yield_per_item"])

        return CollectionAction(
            action_type="search_corroboration",
            source_type=source_type,
            query=query,
            quantity=quantity,
            frequency_hours=0,
            estimated_evidence=evidence,
            estimated_cost=cost,
        )

    def _build_historical_action(self, gap: KnowledgeGap) -> CollectionAction | None:
        """Build a historical collection action (e.g., 30 days of prices)."""
        if not gap.suggested_source_types:
            return None
        source_type = gap.suggested_source_types[0]
        defaults = _SOURCE_DEFAULTS.get(source_type, {"default_quantity": 20, "cost_per_item": 0.2, "evidence_yield_per_item": 0.5})

        # Historical collection: 30 days, 1 item per day
        historical_days = 30
        quantity = historical_days
        cost = quantity * defaults["cost_per_item"] * 0.5  # historical is cheaper (cached)
        evidence = int(quantity * defaults["evidence_yield_per_item"] * 0.7)  # lower yield for historical

        return CollectionAction(
            action_type="historical_collection",
            source_type=source_type,
            query=gap.suggested_queries[0] if gap.suggested_queries else gap.entity_name,
            quantity=quantity,
            historical_days=historical_days,
            estimated_evidence=evidence,
            estimated_cost=cost,
        )

    def _build_frequency_action(self, gap: KnowledgeGap) -> CollectionAction | None:
        """Build an increase-frequency action (for high-priority gaps)."""
        if not gap.suggested_source_types:
            return None
        source_type = gap.suggested_source_types[0]
        defaults = _SOURCE_DEFAULTS.get(source_type, {"default_frequency_hours": 12, "cost_per_item": 0.2})

        # Increase frequency: collect every 6 hours instead of default
        new_frequency = min(6, defaults.get("default_frequency_hours", 12))
        # 4 collections per day × 7 days = 28 items
        quantity = 4 * 7
        cost = quantity * defaults["cost_per_item"] * 0.7  # slight discount for scheduled
        evidence = int(quantity * defaults.get("evidence_yield_per_item", 0.5))

        return CollectionAction(
            action_type="increase_frequency",
            source_type=source_type,
            query=gap.suggested_queries[0] if gap.suggested_queries else gap.entity_name,
            quantity=quantity,
            frequency_hours=new_frequency,
            estimated_evidence=evidence,
            estimated_cost=cost,
        )

    def _build_validation_action(self, gap: KnowledgeGap) -> CollectionAction:
        """Build a schedule-validation action."""
        return CollectionAction(
            action_type="schedule_validation",
            source_type="internal",
            query="",
            quantity=0,
            next_validation_hours=gap.collection_urgency_hours,
            estimated_evidence=0,
            estimated_cost=0.0,
        )

    def _build_minimal_plan(self, gap: KnowledgeGap) -> CollectionPlan:
        """Build a minimal plan (just re-validation) for internal claim types."""
        validation_action = self._build_validation_action(gap)
        import hashlib
        plan_id = "plan_" + hashlib.sha1(f"{gap.gap_id}|minimal".encode()).hexdigest()[:12]

        return CollectionPlan(
            plan_id=plan_id,
            gap_id=gap.gap_id,
            target_entity=gap.entity,
            entity_name=gap.entity_name,
            gap_type=gap.gap_type,
            priority=gap.priority,
            current_confidence=gap.current_confidence,
            target_confidence=gap.target_confidence,
            actions=[validation_action.to_dict()],
            estimated_evidence_gain=0,
            estimated_confidence_lift=0.0,
            total_cost=0.0,
            next_validation_hours=gap.collection_urgency_hours,
        )
