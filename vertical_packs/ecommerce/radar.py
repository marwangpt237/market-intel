"""
E-commerce Radar — Vertical Pack that aggregates product signals into
the "Product: X" intelligence format the user described.

Input: items tagged with metadata["algeria"]["products"] (from AlgeriaProductExtractor)
Output: ProductIntelligenceAggregator stashes aggregated product data on items[0]

Example output (per product):
  Product: Backpacks
    Demand: High
    Saturation: Medium
    Highest-demand wilayas: Algiers, Oran, Constantine
    Average selling price: 3,800 DZD
    Top complaints: Weak zipper, slow delivery
    Best posting hours: 19:00–22:00
    Recommended offer: Free delivery + second item at 30% discount
    Opportunity score: 78/100
"""
from __future__ import annotations
from collections import defaultdict, Counter
from datetime import datetime, timezone
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


class ProductIntelligenceAggregator(BaseProcessor):
    """Aggregates per-product signals across all items.

    For each product category detected, computes:
      - demand_score (0-100): how many mentions + buying signals
      - saturation_score (0-100): how many sellers / mentions
      - top_wilayas: list of (wilaya, mention_count) tuples
      - avg_price_dzd: mean price across all mentions
      - price_range_dzd: (min, max)
      - top_complaints: list of complaint phrases
      - best_posting_hours: list of hours with highest activity
      - recommended_offer: suggested offer strategy
      - opportunity_score: 0-100, composite of demand - saturation + seasonal + low complaints
    """
    name = "product_intelligence_aggregator"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._min_mentions: int = self._config.get("min_mentions", 1)

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        # Aggregate by product category
        product_data: dict[str, dict] = defaultdict(lambda: {
            "mentions": 0,
            "prices": [],
            "wilayas": Counter(),
            "complaints": [],
            "posting_hours": Counter(),
            "buying_signals": 0,
            "sellers": set(),
            "seasonal_signals": [],
            "in_stock_count": 0,
            "out_of_stock_count": 0,
            "discount_mentions": 0,
            "brands": Counter(),
            "sample_items": [],
        })

        for item in items:
            algeria_meta = item.metadata.get("algeria", {})
            products = algeria_meta.get("products", [])
            wilayas = algeria_meta.get("wilayas", [])
            wilaya_names = algeria_meta.get("wilaya_names", [])
            seasonal = algeria_meta.get("seasonal", {})

            # Extract hour from collected_at if available
            hour = None
            if item.collected_at:
                try:
                    dt = datetime.fromisoformat(item.collected_at.replace("Z", "+00:00"))
                    hour = dt.hour
                except (ValueError, TypeError):
                    pass

            for product in products:
                category = product.get("category", "unknown")
                data = product_data[category]

                data["mentions"] += 1

                # Price
                price = product.get("price_dzd")
                if price:
                    data["prices"].append(price)
                price_range = product.get("price_range")
                if price_range:
                    data["prices"].extend(price_range)

                # Wilayas
                for wn in wilaya_names:
                    data["wilayas"][wn] += 1

                # Stock
                if product.get("in_stock") is True:
                    data["in_stock_count"] += 1
                elif product.get("in_stock") is False:
                    data["out_of_stock_count"] += 1

                # Discount
                if product.get("discount_pct"):
                    data["discount_mentions"] += 1

                # Brand
                if product.get("brand"):
                    data["brands"][product["brand"]] += 1

                # Buying signals (from item-level buying_signals)
                buying_signals = item.metadata.get("buying_signals", [])
                data["buying_signals"] += len(buying_signals)

                # Complaints (from item-level pain_points)
                pain_points = item.metadata.get("pain_points", [])
                for pp in pain_points:
                    pp_text = pp.get("text", "")
                    if pp_text:
                        data["complaints"].append(pp_text)

                # Seasonal
                if seasonal.get("seasons"):
                    data["seasonal_signals"].extend(seasonal["seasons"])

                # Posting hour
                if hour is not None:
                    data["posting_hours"][hour] += 1

                # Seller (from author)
                if item.author:
                    data["sellers"].add(item.author)

                # Sample items (cap at 5)
                if len(data["sample_items"]) < 5:
                    data["sample_items"].append({
                        "title": item.title,
                        "url": item.url,
                        "source": item.source_name,
                    })

        # Filter out categories with too few mentions
        filtered_data = {
            cat: data for cat, data in product_data.items()
            if data["mentions"] >= self._min_mentions
        }

        # Compute scores per category
        product_intelligence: list[dict] = []
        for category, data in filtered_data.items():
            intelligence = self._compute_product_intelligence(category, data)
            product_intelligence.append(intelligence)

        # Sort by opportunity score (descending)
        product_intelligence.sort(key=lambda p: p["opportunity_score"], reverse=True)

        # Stash on first item
        if items:
            items[0].metadata["_product_intelligence"] = {
                "products": product_intelligence,
                "total_products": len(product_intelligence),
                "total_mentions": sum(p["demand_count"] for p in product_intelligence),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        self._logger.info(
            f"Product intelligence: {len(product_intelligence)} products aggregated, "
            f"top: {product_intelligence[0]['product'] if product_intelligence else 'none'} "
            f"({product_intelligence[0]['opportunity_score'] if product_intelligence else 0}/100)"
        )
        return items

    def _compute_product_intelligence(self, category: str, data: dict) -> dict:
        """Compute the per-product intelligence dict."""
        # Demand score: based on mentions + buying signals
        demand_raw = data["mentions"] * 5 + data["buying_signals"] * 10
        demand_score = min(100, demand_raw)
        demand_label = self._score_to_label(demand_score)

        # Saturation score: based on number of distinct sellers + total mentions
        saturation_raw = len(data["sellers"]) * 8 + data["mentions"] * 3
        saturation_score = min(100, saturation_raw)
        saturation_label = self._score_to_label(saturation_score, inverse=True)  # inverse: high score = high saturation = bad

        # Top wilayas (sorted by mention count)
        top_wilayas = [w for w, _ in data["wilayas"].most_common(5)]

        # Average price
        prices = data["prices"]
        avg_price = int(sum(prices) / len(prices)) if prices else None
        price_range = (min(prices), max(prices)) if prices else None

        # Top complaints (dedupe + top 3)
        complaint_counter = Counter(data["complaints"])
        top_complaints = [c for c, _ in complaint_counter.most_common(3)]

        # Best posting hours
        top_hours_raw = data["posting_hours"].most_common(3)
        best_posting_hours = [f"{h:02d}:00" for h, _ in top_hours_raw]
        if best_posting_hours:
            # Convert to range format if hours are consecutive
            best_posting_hours_str = self._format_hour_range(top_hours_raw)
        else:
            best_posting_hours_str = "19:00–22:00"  # default Algerian peak hours

        # Recommended offer
        recommended_offer = self._generate_offer_recommendation(
            category, avg_price, data["discount_mentions"], data["mentions"]
        )

        # Opportunity score: demand - saturation + seasonal bonus + stock signal
        seasonal_bonus = 10 if data["seasonal_signals"] else 0
        stock_signal = 5 if data["in_stock_count"] > data["out_of_stock_count"] else -5
        opportunity_score = max(0, min(100, int(
            demand_score * 0.5
            + (100 - saturation_score) * 0.3  # inverse saturation
            + seasonal_bonus
            + stock_signal
        )))

        return {
            "product": category.replace("_", " ").title(),
            "category": category,
            "demand": demand_label,
            "demand_score": demand_score,
            "demand_count": data["mentions"],
            "saturation": saturation_label,
            "saturation_score": saturation_score,
            "seller_count": len(data["sellers"]),
            "highest_demand_wilayas": top_wilayas,
            "average_selling_price_dzd": avg_price,
            "price_range_dzd": price_range,
            "top_complaints": top_complaints,
            "best_posting_hours": best_posting_hours_str,
            "recommended_offer": recommended_offer,
            "opportunity_score": opportunity_score,
            "buying_signals": data["buying_signals"],
            "seasonal_signals": list(set(data["seasonal_signals"])),
            "top_brands": [b for b, _ in data["brands"].most_common(3)],
            "stock_status": {
                "in_stock": data["in_stock_count"],
                "out_of_stock": data["out_of_stock_count"],
            },
            "discount_mentions": data["discount_mentions"],
            "sample_items": data["sample_items"],
        }

    @staticmethod
    def _score_to_label(score: int, inverse: bool = False) -> str:
        """Convert 0-100 score to High/Medium/Low label.

        If inverse=True, high score means bad (saturation).
        """
        if not inverse:
            if score >= 60:
                return "High"
            elif score >= 30:
                return "Medium"
            else:
                return "Low"
        else:
            if score >= 60:
                return "High"
            elif score >= 30:
                return "Medium"
            else:
                return "Low"

    @staticmethod
    def _format_hour_range(hours_with_counts: list[tuple[int, int]]) -> str:
        """Format posting hours as a range string."""
        if not hours_with_counts:
            return "19:00–22:00"
        hours = sorted([h for h, _ in hours_with_counts])
        if len(hours) == 1:
            return f"{hours[0]:02d}:00–{hours[0]+1:02d}:00"
        return f"{hours[0]:02d}:00–{hours[-1]+1:02d}:00"

    @staticmethod
    def _generate_offer_recommendation(category: str, avg_price: int | None, discount_count: int, mention_count: int) -> str:
        """Generate a recommended offer strategy."""
        parts = []

        # Free delivery is universally appealing
        if mention_count >= 3:
            parts.append("Free delivery")

        # Bundle / second-item discount if price is mid-range
        if avg_price and 1000 <= avg_price <= 10000:
            parts.append("second item at 30% discount")

        # If no discounts mentioned by competitors, suggest one
        if discount_count == 0 and avg_price:
            parts.append(f"introductory 15% off (first 50 customers)")

        # Category-specific recommendations
        if category == "clothing":
            parts.append("free size exchange within 7 days")
        elif category == "electronics":
            parts.append("6-month warranty")
        elif category == "beauty":
            parts.append("free sample with first order")
        elif category == "food":
            parts.append("freshness guarantee or money back")

        if not parts:
            return "Free delivery + competitive pricing"

        return " + ".join(parts[:3])  # cap at 3 parts


class EcommerceVerticalPack:
    """E-commerce Radar vertical pack.

    Bundles:
      - ProductIntelligenceAggregator processor
      - (Future) ProductIntelligenceReport generator
    """

    vertical_name = "ecommerce"
    description = "E-commerce Radar — product demand, saturation, and opportunity intelligence"

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    def get_processors(self) -> list:
        return [
            ProductIntelligenceAggregator(self._config.get("product_aggregator", {})),
        ]


# Auto-register
from vertical_packs.base import register_vertical_pack
register_vertical_pack("ecommerce", EcommerceVerticalPack)
