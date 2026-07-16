"""
Claim Extractor — converts processor outputs into Claim objects.

For each item, extracts claims of various types:
  - Product prices → AVERAGE_PRICE, PRICE_RANGE claims
  - Demand signals → DEMAND_LEVEL claims
  - Trends → TREND claims
  - Wilaya mentions → WILAYA_DEMAND claims
  - Seasonal signals → SEASONAL_SIGNAL claims
  - Stock status → STOCK_STATUS claims
  - Pain points → PAIN_POINT claims
  - Buying signals → BUYING_SIGNAL claims
  - Opportunity scores → OPPORTUNITY_SCORE claims
  - Decision ROI → DECISION_ROI claims

Each claim gets Evidence objects built from the source item, with
source_id, source_type, source_reliability (from TrustLayer).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from core.models import ProcessedItem
from core.logger import get_logger
from validation.models import Claim, Evidence, ClaimType, compute_claim_id
from validation.trust_layer import TrustLayer


class ClaimExtractor:
    """Extracts Claim objects from ProcessedItems + their metadata.

    Walks each item's metadata and produces Claim + Evidence pairs.
    """

    def __init__(self, trust_layer: TrustLayer, config: dict | None = None):
        self._trust_layer = trust_layer
        self._config = config or {}
        self._logger = get_logger("claim_extractor")

    def extract_from_items(self, items: list[ProcessedItem]) -> list[tuple[Claim, list[Evidence]]]:
        """Extract all claims from a list of items.

        Returns: list of (Claim, [Evidence, ...]) tuples.
        Multiple items contributing to the same claim get merged at the
        ClaimStore level (same claim_id → upsert).
        """
        claims_with_evidence: list[tuple[Claim, list[Evidence]]] = []

        for item in items:
            # Build a base Evidence object for this item
            source_id = self._compute_source_id(item)
            source_type = item.source or "unknown"
            source_name = item.source_name or ""
            source_reliability = self._trust_layer.get_reliability(source_id, source_type, source_name)

            base_evidence_kwargs = {
                "source_id": source_id,
                "source_type": source_type,
                "source_reliability": source_reliability,
                "item_id": item.id,
                "item_url": item.url,
                "item_title": item.title,
                "collected_at": item.collected_at,
            }

            # Extract claims from algeria metadata (if present)
            algeria = item.metadata.get("algeria", {})
            if algeria:
                claims_with_evidence.extend(
                    self._extract_algeria_claims(item, algeria, base_evidence_kwargs)
                )

            # Extract claims from generic processor outputs
            claims_with_evidence.extend(
                self._extract_generic_claims(item, base_evidence_kwargs)
            )

        # Extract claims from aggregated intelligence (on items[0])
        if items:
            claims_with_evidence.extend(
                self._extract_aggregated_claims(items[0], items)
            )

        return claims_with_evidence

    def _compute_source_id(self, item: ProcessedItem) -> str:
        """Compute a stable source_id from an item."""
        # Try source_name first (more meaningful than URL domain)
        if item.source_name:
            name_lower = item.source_name.lower()
            # Check for known high-credibility sources
            for pattern in ["aps.dz", "aps algeria", "aps ",
                            "elwatan", "tsa-algerie", "tsa algerie",
                            "liberte-algerie", "liberte algerie",
                            "searchenginejournal", "hubspot", "marketing land",
                            "hacker news", "github"]:
                if pattern in name_lower:
                    return pattern.replace(" ", "_").rstrip("_")

        # Fall back to URL domain for RSS
        if item.source == "rss" and item.url:
            from urllib.parse import urlparse
            try:
                parsed = urlparse(item.url)
                if parsed.netloc:
                    return parsed.netloc.replace("www.", "")
            except Exception:
                pass

        # Fall back to source_name slugified
        if item.source_name:
            return item.source_name.lower().replace(" ", "_")[:50]

        # Last resort: source type
        if item.source == "reddit" and item.source_name:
            return f"reddit:{item.source_name.lower()}"
        elif item.source == "hacker_news":
            return "hacker_news"
        elif item.source:
            return item.source
        return "unknown"

    def _extract_algeria_claims(
        self,
        item: ProcessedItem,
        algeria: dict,
        base_ev_kwargs: dict,
    ) -> list[tuple[Claim, list[Evidence]]]:
        """Extract claims from Algeria Pack metadata."""
        results: list[tuple[Claim, list[Evidence]]] = []

        # Products → AVERAGE_PRICE claims
        for product in algeria.get("products", []):
            category = product.get("category", "unknown")
            entity = f"product:{category}"

            # Price claim
            if product.get("price_dzd") is not None:
                claim = Claim(
                    id=compute_claim_id(entity, ClaimType.AVERAGE_PRICE.value, product["price_dzd"]),
                    entity=entity,
                    claim_type=ClaimType.AVERAGE_PRICE.value,
                    value=product["price_dzd"],
                    value_unit="DZD",
                )
                evidence = Evidence(
                    value=product["price_dzd"],
                    supports=True,
                    confidence=1.0,
                    **base_ev_kwargs,
                )
                results.append((claim, [evidence]))

            # Price range claim
            if product.get("price_range"):
                pr = product["price_range"]
                claim = Claim(
                    id=compute_claim_id(entity, ClaimType.PRICE_RANGE.value, pr),
                    entity=entity,
                    claim_type=ClaimType.PRICE_RANGE.value,
                    value=pr,
                    value_unit="DZD",
                )
                evidence = Evidence(
                    value=pr,
                    supports=True,
                    confidence=1.0,
                    **base_ev_kwargs,
                )
                results.append((claim, [evidence]))

            # Stock status claim
            if product.get("in_stock") is not None:
                stock_value = "in_stock" if product["in_stock"] else "out_of_stock"
                claim = Claim(
                    id=compute_claim_id(entity, ClaimType.STOCK_STATUS.value, stock_value),
                    entity=entity,
                    claim_type=ClaimType.STOCK_STATUS.value,
                    value=stock_value,
                )
                evidence = Evidence(
                    value=stock_value,
                    supports=True,
                    confidence=1.0,
                    **base_ev_kwargs,
                )
                results.append((claim, [evidence]))

        # Wilayas → WILAYA_DEMAND claims
        for wilaya_name in algeria.get("wilaya_names", []):
            entity = f"wilaya:{wilaya_name}"
            claim = Claim(
                id=compute_claim_id(entity, ClaimType.WILAYA_DEMAND.value, "mentioned"),
                entity=entity,
                claim_type=ClaimType.WILAYA_DEMAND.value,
                value="mentioned",
            )
            evidence = Evidence(
                value="mentioned",
                supports=True,
                confidence=1.0,
                **base_ev_kwargs,
            )
            results.append((claim, [evidence]))

        # Seasonal signals → SEASONAL_SIGNAL claims
        seasonal = algeria.get("seasonal", {})
        for season in seasonal.get("seasons", []):
            entity = f"season:{season}"
            claim = Claim(
                id=compute_claim_id(entity, ClaimType.SEASONAL_SIGNAL.value, "active"),
                entity=entity,
                claim_type=ClaimType.SEASONAL_SIGNAL.value,
                value="active",
            )
            evidence = Evidence(
                value="active",
                supports=True,
                confidence=1.0,
                **base_ev_kwargs,
            )
            results.append((claim, [evidence]))

        # Payment methods → METRIC claims (track adoption)
        for method in algeria.get("payment_methods", []):
            entity = f"payment_method:{method}"
            claim = Claim(
                id=compute_claim_id(entity, ClaimType.METRIC.value, "accepted"),
                entity=entity,
                claim_type=ClaimType.METRIC.value,
                value="accepted",
            )
            evidence = Evidence(
                value="accepted",
                supports=True,
                confidence=1.0,
                **base_ev_kwargs,
            )
            results.append((claim, [evidence]))

        return results

    def _extract_generic_claims(
        self,
        item: ProcessedItem,
        base_ev_kwargs: dict,
    ) -> list[tuple[Claim, list[Evidence]]]:
        """Extract claims from generic processor outputs."""
        results: list[tuple[Claim, list[Evidence]]] = []

        # Entities → ENTITY_MENTION claims
        entities = item.metadata.get("entities", {})
        for company in entities.get("companies", []):
            entity = f"company:{company.lower()}"
            claim = Claim(
                id=compute_claim_id(entity, ClaimType.ENTITY_MENTION.value, "mentioned"),
                entity=entity,
                claim_type=ClaimType.ENTITY_MENTION.value,
                value="mentioned",
            )
            evidence = Evidence(
                value="mentioned",
                supports=True,
                confidence=1.0,
                **base_ev_kwargs,
            )
            results.append((claim, [evidence]))

        # Pain points → PAIN_POINT claims
        for pp in item.metadata.get("pain_points", []):
            category = pp.get("category", "unknown")
            entity = f"pain_point:{category}"
            claim = Claim(
                id=compute_claim_id(entity, ClaimType.PAIN_POINT.value, "reported"),
                entity=entity,
                claim_type=ClaimType.PAIN_POINT.value,
                value="reported",
            )
            evidence = Evidence(
                value="reported",
                supports=True,
                confidence=1.0,
                **base_ev_kwargs,
            )
            results.append((claim, [evidence]))

        # Buying signals → BUYING_SIGNAL claims
        for bs in item.metadata.get("buying_signals", []):
            bs_type = bs.get("type", "unknown")
            entity = f"buying_signal:{bs_type}"
            claim = Claim(
                id=compute_claim_id(entity, ClaimType.BUYING_SIGNAL.value, "detected"),
                entity=entity,
                claim_type=ClaimType.BUYING_SIGNAL.value,
                value="detected",
            )
            evidence = Evidence(
                value="detected",
                supports=True,
                confidence=bs.get("confidence", 1.0),
                **base_ev_kwargs,
            )
            results.append((claim, [evidence]))

        # Trend → TREND claim
        trend = item.metadata.get("trend")
        if trend and trend != "stable":
            cluster_label = item.metadata.get("cluster_label", "uncategorized")
            entity = f"topic:{cluster_label}"
            claim = Claim(
                id=compute_claim_id(entity, ClaimType.TREND.value, trend),
                entity=entity,
                claim_type=ClaimType.TREND.value,
                value=trend,
            )
            evidence = Evidence(
                value=trend,
                supports=True,
                confidence=1.0,
                **base_ev_kwargs,
            )
            results.append((claim, [evidence]))

        return results

    def _extract_aggregated_claims(
        self,
        first_item: ProcessedItem,
        all_items: list[ProcessedItem],
    ) -> list[tuple[Claim, list[Evidence]]]:
        """Extract claims from aggregated intelligence (on items[0]).

        These are claims that aggregate across all items — e.g. opportunity
        scores, demand levels, recommended offers.
        """
        results: list[tuple[Claim, list[Evidence]]] = []

        # Product intelligence (from E-commerce Radar)
        product_intel = first_item.metadata.get("_product_intelligence", {})
        for product in product_intel.get("products", []):
            category = product.get("category", "unknown")
            entity = f"product:{category}"

            # Opportunity score claim
            opp_score = product.get("opportunity_score")
            if opp_score is not None:
                claim = Claim(
                    id=compute_claim_id(entity, ClaimType.OPPORTUNITY_SCORE.value, opp_score),
                    entity=entity,
                    claim_type=ClaimType.OPPORTUNITY_SCORE.value,
                    value=opp_score,
                )
                # Build evidence from sample items
                evidence_list = []
                for sample in product.get("sample_items", [])[:3]:
                    source_id = sample.get("source", "unknown").lower().replace(" ", "_")[:50]
                    source_reliability = self._trust_layer.get_reliability(source_id)
                    evidence_list.append(Evidence(
                        source_id=source_id,
                        source_type="aggregated",
                        source_reliability=source_reliability,
                        value=opp_score,
                        item_url=sample.get("url"),
                        item_title=sample.get("title"),
                        supports=True,
                        confidence=0.7,  # aggregated evidence is medium-confidence
                    ))
                if evidence_list:
                    results.append((claim, evidence_list))

            # Demand level claim
            demand = product.get("demand")
            if demand:
                claim = Claim(
                    id=compute_claim_id(entity, ClaimType.DEMAND_LEVEL.value, demand),
                    entity=entity,
                    claim_type=ClaimType.DEMAND_LEVEL.value,
                    value=demand,
                )
                evidence_list = []
                for sample in product.get("sample_items", [])[:3]:
                    source_id = sample.get("source", "unknown").lower().replace(" ", "_")[:50]
                    source_reliability = self._trust_layer.get_reliability(source_id)
                    evidence_list.append(Evidence(
                        source_id=source_id,
                        source_type="aggregated",
                        source_reliability=source_reliability,
                        value=demand,
                        item_url=sample.get("url"),
                        item_title=sample.get("title"),
                        supports=True,
                        confidence=0.6,
                    ))
                if evidence_list:
                    results.append((claim, evidence_list))

        # Decision ROI claims (from Strategy Engine output)
        strategy = first_item.metadata.get("_strategy", {})
        for selected in strategy.get("selected", []):
            decision = selected.get("decision", {})
            target = decision.get("target", "unknown")
            entity = f"decision:{target}"
            roi = selected.get("roi")
            if roi is not None:
                claim = Claim(
                    id=compute_claim_id(entity, ClaimType.DECISION_ROI.value, roi),
                    entity=entity,
                    claim_type=ClaimType.DECISION_ROI.value,
                    value=roi,
                )
                evidence = Evidence(
                    source_id="strategy_engine",
                    source_type="aggregated",
                    source_reliability=0.75,
                    value=roi,
                    supports=True,
                    confidence=0.7,
                )
                results.append((claim, [evidence]))

        return results
