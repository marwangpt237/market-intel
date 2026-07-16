"""
Product Intelligence Report — outputs the "Product: X" style format.

Example output:
  ## Product: Backpacks
  - Demand: High
  - Saturation: Medium
  - Highest-demand wilayas: Algiers, Oran, Constantine
  - Average selling price: 3,800 DZD
  - Top complaints: Weak zipper, slow delivery
  - Best posting hours: 19:00–22:00
  - Recommended offer: Free delivery + second item at 30% discount
  - Opportunity score: 78/100

Sections:
  1. Executive Summary (top 3 opportunities)
  2. Product Intelligence Cards (one per detected product)
  3. Wilaya Demand Heatmap (which wilayas have most activity)
  4. Seasonal Insights
  5. Pricing Insights (sweet spot analysis)
  6. Saturation Warnings
  7. Closed-loop status
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from core.models import ProcessedItem
from core.logger import get_logger
from reports.base import BaseReportGenerator


class ProductIntelligenceReportGenerator(BaseReportGenerator):
    name = "product_intelligence"

    def __init__(self, config: dict):
        super().__init__(config)
        self._output_path = Path(config.get("output_path", "reports/"))
        self._top_products = int(config.get("top_products_count", 20))

    def _generate(self, items: list[ProcessedItem], run_id: str) -> str:
        self._output_path.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        # Find product intelligence data
        intel_data = None
        for item in items:
            if "_product_intelligence" in item.metadata:
                intel_data = item.metadata["_product_intelligence"]
                break

        lines: list[str] = []
        lines.append(f"# Product Intelligence Report — Algeria — {date_str}")
        lines.append("")
        lines.append(f"_Generated: {now.isoformat()} | Run: `{run_id}`_")
        lines.append("")
        lines.append("> Algeria-first market intelligence — product-level demand, saturation, and opportunity analysis.")
        lines.append("")

        if not intel_data or not intel_data.get("products"):
            lines.append("_No product intelligence data available this run._")
            lines.append("_Make sure Algeria Pack processors (product_extractor, wilaya_extractor) are enabled._")
            filepath = self._output_path / f"product_intelligence_{date_str}_{run_id}.md"
            filepath.write_text("\n".join(lines), encoding="utf-8")
            return str(filepath)

        products = intel_data["products"][: self._top_products]
        total_mentions = intel_data.get("total_mentions", 0)

        # ─── Executive Summary ───────────────────────────────────────────
        lines.append("## Executive Summary")
        lines.append("")
        lines.append(f"- **Products detected:** {intel_data['total_products']}")
        lines.append(f"- **Total mentions:** {total_mentions}")
        lines.append(f"- **Top opportunity:** {products[0]['product']} (score: {products[0]['opportunity_score']}/100)" if products else "- No products detected")
        lines.append("")

        if products:
            # Top 3 opportunities
            top_3 = [p for p in products if p["opportunity_score"] >= 30][:3]
            if top_3:
                lines.append("**Top 3 opportunities to act on this week:**")
                lines.append("")
                for i, p in enumerate(top_3, 1):
                    lines.append(f"{i}. **{p['product']}** — opportunity score {p['opportunity_score']}/100")
                    lines.append(f"   - Demand: {p['demand']} ({p['demand_count']} mentions)")
                    if p["average_selling_price_dzd"]:
                        lines.append(f"   - Avg price: {p['average_selling_price_dzd']:,} DZD")
                    if p["highest_demand_wilayas"]:
                        lines.append(f"   - Top wilayas: {', '.join(p['highest_demand_wilayas'][:3])}")
                    lines.append(f"   - Recommended offer: {p['recommended_offer']}")
                lines.append("")

        # ─── Product Intelligence Cards ──────────────────────────────────
        lines.append(f"## Product Intelligence Cards ({len(products)})")
        lines.append("")
        lines.append("> Each card aggregates signals across all collected items mentioning this product.")
        lines.append("")

        for i, p in enumerate(products, 1):
            lines.append(f"### {i}. Product: {p['product'].title()}")
            lines.append("")
            lines.append(f"- **Demand:** {p['demand']} (score: {p['demand_score']}/100, {p['demand_count']} mentions)")
            lines.append(f"- **Saturation:** {p['saturation']} (score: {p['saturation_score']}/100, {p['seller_count']} sellers)")
            if p["highest_demand_wilayas"]:
                lines.append(f"- **Highest-demand wilayas:** {', '.join(p['highest_demand_wilayas'])}")
            else:
                lines.append(f"- **Highest-demand wilayas:** _not enough location data_")
            if p["average_selling_price_dzd"]:
                price_str = f"{p['average_selling_price_dzd']:,} DZD"
                if p["price_range_dzd"]:
                    price_str += f" (range: {p['price_range_dzd'][0]:,}–{p['price_range_dzd'][1]:,} DZD)"
                lines.append(f"- **Average selling price:** {price_str}")
            else:
                lines.append(f"- **Average selling price:** _no price data_")
            if p["top_complaints"]:
                lines.append(f"- **Top complaints:** {', '.join(p['top_complaints'])}")
            else:
                lines.append(f"- **Top complaints:** _none detected_")
            lines.append(f"- **Best posting hours:** {p['best_posting_hours']}")
            lines.append(f"- **Recommended offer:** {p['recommended_offer']}")
            lines.append(f"- **Opportunity score:** **{p['opportunity_score']}/100**")
            lines.append("")

            # Additional details
            extras = []
            if p["buying_signals"]:
                extras.append(f"buying signals: {p['buying_signals']}")
            if p["seasonal_signals"]:
                extras.append(f"seasonal: {', '.join(p['seasonal_signals'])}")
            if p["top_brands"]:
                extras.append(f"top brands: {', '.join(p['top_brands'])}")
            stock = p["stock_status"]
            if stock["in_stock"] or stock["out_of_stock"]:
                extras.append(f"stock: {stock['in_stock']} in / {stock['out_of_stock']} out")
            if p["discount_mentions"]:
                extras.append(f"discounts mentioned: {p['discount_mentions']}")

            if extras:
                lines.append(f"  _Details: {' · '.join(extras)}_")
                lines.append("")

            # Sample items
            if p["sample_items"]:
                lines.append("  **Sample listings:**")
                for sample in p["sample_items"][:3]:
                    lines.append(f"  - [{sample['title'][:80]}]({sample['url']}) — _{sample['source']}_")
                lines.append("")

        # ─── Wilaya Demand Heatmap ───────────────────────────────────────
        lines.append("## Wilaya Demand Heatmap")
        lines.append("")
        wilaya_totals: Counter = Counter()
        for p in products:
            # Each product contributes its wilaya mentions
            for w in p["highest_demand_wilayas"]:
                wilaya_totals[w] += 1

        if wilaya_totals:
            lines.append("| Rank | Wilaya | Products Mentioning |")
            lines.append("|------|--------|---------------------|")
            for i, (w, count) in enumerate(wilaya_totals.most_common(15), 1):
                lines.append(f"| {i} | {w} | {count} |")
            lines.append("")
        else:
            lines.append("_No wilaya data detected. Ensure WilayaExtractor is enabled._")
            lines.append("")

        # ─── Seasonal Insights ───────────────────────────────────────────
        lines.append("## Seasonal Insights")
        lines.append("")
        seasonal_products: dict[str, list[str]] = {}
        for p in products:
            for season in p["seasonal_signals"]:
                if season not in seasonal_products:
                    seasonal_products[season] = []
                seasonal_products[season].append(p["product"])

        if seasonal_products:
            lines.append("| Season | Products Affected |")
            lines.append("|--------|-------------------|")
            for season, prods in seasonal_products.items():
                lines.append(f"| {season.replace('_', ' ').title()} | {', '.join(prods[:5])} |")
            lines.append("")
        else:
            lines.append("_No seasonal signals detected this run._")
            lines.append("")

        # ─── Pricing Insights ────────────────────────────────────────────
        lines.append("## Pricing Insights")
        lines.append("")
        priced_products = [p for p in products if p["average_selling_price_dzd"]]
        if priced_products:
            all_prices = []
            for p in priced_products:
                all_prices.extend([p["average_selling_price_dzd"]])

            if all_prices:
                avg_price = int(sum(all_prices) / len(all_prices))
                min_price = min(all_prices)
                max_price = max(all_prices)

                lines.append(f"- **Price range observed:** {min_price:,} – {max_price:,} DZD")
                lines.append(f"- **Average across all products:** {avg_price:,} DZD")
                lines.append("")

                # Sweet spot analysis (most common price bucket)
                price_buckets = Counter()
                for price in all_prices:
                    bucket = (price // 1000) * 1000  # round to nearest 1000
                    price_buckets[bucket] += 1

                if price_buckets:
                    most_common_bucket, most_common_count = price_buckets.most_common(1)[0]
                    lines.append(f"- **Sweet spot:** {most_common_bucket:,}–{most_common_bucket + 1000:,} DZD ({most_common_count} products in this range)")
                    lines.append("")
        else:
            lines.append("_No pricing data detected this run._")
            lines.append("")

        # ─── Saturation Warnings ─────────────────────────────────────────
        lines.append("## Saturation Warnings")
        lines.append("")
        saturated = [p for p in products if p["saturation"] == "High"]
        if saturated:
            lines.append("_These products have many sellers — entering this market requires differentiation._")
            lines.append("")
            for p in saturated:
                lines.append(f"- **{p['product']}** — {p['seller_count']} sellers, saturation score {p['saturation_score']}/100")
            lines.append("")
        else:
            lines.append("_No highly-saturated products detected._")
            lines.append("")

        # ─── Closed-loop status ──────────────────────────────────────────
        lines.append("## Closed-Loop Status")
        lines.append("")
        lines.append(f"- ✅ **Collect** — {len(items)} items from Algeria-tuned sources")
        lines.append(f"- ✅ **Algeria Pack** — WilayaExtractor, DarijaNLP, PaymentDetector, SeasonalDetector, ProductExtractor ran")
        lines.append(f"- ✅ **Aggregate** — {intel_data['total_products']} products aggregated")
        lines.append(f"- ✅ **Score** — Opportunity score computed per product")
        lines.append(f"- ✅ **Report** — Product intelligence cards generated")
        lines.append(f"- ⏸ **Act** — Manual: act on top opportunities (post listings, run campaigns)")
        lines.append(f"- ⏸ **Measure** — Outcomes tracked via metrics_input_template.json")
        lines.append(f"- ⏸ **Learn** — Opportunity score weights tune over time")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("_Market-Intel — Algeria Pack v1 + E-commerce Radar vertical._")
        lines.append("_Long-term moat: proprietary regional intelligence that global products cannot match._")

        filepath = self._output_path / f"product_intelligence_{date_str}_{run_id}.md"
        filepath.write_text("\n".join(lines), encoding="utf-8")

        self._logger.info(f"Product intelligence report written to {filepath} ({len(products)} products)")
        return str(filepath)
