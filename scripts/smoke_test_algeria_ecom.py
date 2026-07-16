"""Smoke test for algeria_ecom profile — Algeria Pack + E-commerce Radar."""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from core.models import RawItem, ProcessedItem
from workflows.daily_run import DailyRun
from core.config_loader import load_config
from reports.product_intelligence_report import ProductIntelligenceReportGenerator


def test_algeria_ecom_profile_end_to_end():
    tmpdir = tempfile.mkdtemp()
    try:
        config = load_config("config.algeria_ecom.yaml")
        cfg_dict = config.to_dict()
        cfg_dict["storage"]["path"] = os.path.join(tmpdir, "algeria_ecom.db")
        cfg_dict["reports"]["intelligence"]["output_path"] = os.path.join(tmpdir, "reports")
        cfg_dict["reports"]["strategy"]["output_path"] = os.path.join(tmpdir, "reports")
        cfg_dict["reports"]["learning"]["output_path"] = os.path.join(tmpdir, "reports")
        cfg_dict["reports"]["product_intelligence"]["output_path"] = os.path.join(tmpdir, "reports")
        cfg_dict["processors"]["execution_engine"]["output_path"] = os.path.join(tmpdir, "actions")

        for cname in cfg_dict.get("collectors", {}):
            cfg_dict["collectors"][cname]["enabled"] = False

        from config.loader import Config
        config = Config(cfg_dict)
        workflow = DailyRun(config)

        # Mock items — realistic Algerian e-commerce signals
        mock_raw = [
            RawItem.create(
                source="rss", source_name="Algerian Commerce",
                title="Vente sac à dos 3500 DA à Alger, livraison Oran",
                url="http://1.com",
                body="Sac à dos neuf, en stock. Paiement CCP ou cash. Promo 15% pour Ramadan. Contactez 0555123456.",
                author="seller1", score=20,
            ),
            RawItem.create(
                source="rss", source_name="Algerian Commerce",
                title="telephone Samsung 12000 DA Alger, Edahabia acceptée",
                url="http://2.com",
                body="Téléphone neuf, garantie 6 mois. Livraison nationale. Paiement Edahabia ou BaridiMob.",
                author="seller2", score=35,
            ),
            RawItem.create(
                source="rss", source_name="Algerian Commerce",
                title="Sac à dos 2800 DA Constantine, rupture de stock",
                url="http://3.com",
                body="Épuisé. Revenir la semaine prochaine. CCP: 0021345698.",
                author="seller3", score=15,
            ),
            RawItem.create(
                source="rss", source_name="Algerian Commerce",
                title="بيع حذاء Nike 6000 دج في وهران",
                url="http://4.com",
                body="جديد، توصيل لكل الولايات. الدفع CCP أو كاش. خصم 10% لشهر رمضان.",
                author="seller4", score=42,
            ),
            RawItem.create(
                source="rss", source_name="Algerian Commerce",
                title="Robe algérienne 4500 DA, livraison nationale",
                url="http://5.com",
                body="Neuf, parfait pour Aïd El Fitr. Tailles M/L/XL. Paiement cash ou CCP.",
                author="seller5", score=28,
            ),
            RawItem.create(
                source="rss", source_name="Algerian Commerce",
                title="iPhone 14 95000 DA Alger, paiement CIB",
                url="http://6.com",
                body="Occasion, parfait état. Garantie 3 mois. Carte CIB acceptée. Livraison Alger uniquement.",
                author="seller6", score=51,
            ),
        ]

        processed = [ProcessedItem.from_raw(r) for r in mock_raw]

        # Run all processors
        processors = workflow._container.get_processors()
        print(f"\nRunning {len(processors)} processors:")
        for name, processor in processors.items():
            try:
                processed = processor.process(processed)
                print(f"  ✓ {name}: {len(processed)} items after")
            except Exception as e:
                print(f"  ✗ {name} failed: {e}")
                import traceback
                traceback.print_exc()

        # Storage
        storage = workflow._container.get_storage()
        storage.save([workflow._processed_to_dict(item) for item in processed], workflow._run_id)

        # Reports
        report_gen = workflow._container.get_report_generator()
        report_path = report_gen.generate(processed, workflow._run_id)
        print(f"\n  ✓ Intelligence report: {report_path}")

        # Product intelligence report (THE primary output)
        pi_path = ProductIntelligenceReportGenerator(cfg_dict["reports"]["product_intelligence"]).generate(processed, workflow._run_id)
        print(f"  ✓ Product intelligence report: {pi_path}")

        # Show summary
        print()
        print("=" * 70)
        # Find items with algeria metadata
        algeria_items = [i for i in processed if i.metadata.get("algeria")]
        print(f"  Total items:           {len(processed)}")
        print(f"  Items with Algeria metadata: {len(algeria_items)}")

        # Show per-processor tagging
        darija_items = sum(1 for i in processed if i.metadata.get("algeria", {}).get("language", {}).get("darija_terms_count", 0) > 0)
        wilaya_items = sum(1 for i in processed if i.metadata.get("algeria", {}).get("wilayas"))
        payment_items = sum(1 for i in processed if i.metadata.get("algeria", {}).get("payment_methods"))
        seasonal_items = sum(1 for i in processed if i.metadata.get("algeria", {}).get("seasonal"))
        product_items = sum(1 for i in processed if i.metadata.get("algeria", {}).get("products"))
        print(f"  Darija NLP tagged:     {darija_items}")
        print(f"  Wilaya tagged:         {wilaya_items}")
        print(f"  Payment methods tagged: {payment_items}")
        print(f"  Seasonal tagged:       {seasonal_items}")
        print(f"  Products tagged:       {product_items}")

        # Show product intelligence
        for item in processed:
            if "_product_intelligence" in item.metadata:
                intel = item.metadata["_product_intelligence"]
                print()
                print(f"  Products aggregated:   {intel['total_products']}")
                print(f"  Total mentions:        {intel['total_mentions']}")
                print()
                print("  Top products by opportunity score:")
                for p in intel["products"][:5]:
                    print(f"    {p['product']:20s} | score {p['opportunity_score']:>3}/100 | demand {p['demand']:6s} | {p['demand_count']} mentions | avg {p.get('average_selling_price_dzd', 'N/A')} DZD")
                break

        # Print first 120 lines of product intelligence report
        print()
        print("=" * 70)
        print("  PRODUCT INTELLIGENCE REPORT (first 120 lines):")
        print("=" * 70)
        with open(pi_path) as f:
            for i, line in enumerate(f):
                if i >= 120:
                    break
                print(f"  {line.rstrip()}")
        print("=" * 70)

        print("\n✓ Algeria e-commerce profile ran successfully")
        return True

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    success = test_algeria_ecom_profile_end_to_end()
    sys.exit(0 if success else 1)
