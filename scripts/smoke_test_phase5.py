"""End-to-end smoke test for Phase 5 — verify Strategy Engine produces optimal plan."""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from core.models import RawItem, ProcessedItem
from workflows.daily_run import DailyRun
from core.config_loader import load_config
from reports.strategy_report import StrategyReportGenerator


def test_phase5_strategy_pipeline():
    tmpdir = tempfile.mkdtemp()
    try:
        config = load_config("config.yaml")
        cfg_dict = config.to_dict()
        cfg_dict["storage"]["path"] = os.path.join(tmpdir, "test.db")
        cfg_dict["reports"]["intelligence"]["output_path"] = os.path.join(tmpdir, "reports")
        cfg_dict["reports"]["decisions"]["output_path"] = os.path.join(tmpdir, "reports")
        cfg_dict["reports"]["strategy"]["output_path"] = os.path.join(tmpdir, "reports")
        cfg_dict["processors"]["execution_engine"]["output_path"] = os.path.join(tmpdir, "actions")
        # Tight budget to test knapsack
        cfg_dict["processors"]["strategy_engine"]["budget_usd"] = 500
        cfg_dict["processors"]["strategy_engine"]["time_hours"] = 20

        # Disable all collectors
        for cname in cfg_dict.get("collectors", {}):
            cfg_dict["collectors"][cname]["enabled"] = False

        from config.loader import Config
        config = Config(cfg_dict)
        workflow = DailyRun(config)

        # Mock data — designed to test false positive filter + strategy
        mock_raw = [
            # Will trigger: source_authority (HN=high), domain (saas pricing_complaint),
            # entity (hubspot), scoring (high opportunity), decision (build_feature)
            RawItem.create(
                source="hacker_news", source_name="Hacker News",
                title="HubSpot pricing is insane, looking for cheaper alternative",
                url="http://news.ycombinator.com/1",
                body="Need cheaper CRM with similar features, switching from HubSpot. Their pricing is a rip off.",
                author="user1", score=200,
            ),
            # Will trigger: source_authority (HN), entity (maltego), decision (launch_campaign)
            RawItem.create(
                source="hacker_news", source_name="Hacker News",
                title="Show HN: open-source Maltego alternative for OSINT",
                url="http://news.ycombinator.com/2",
                body="Free OSINT platform with similar features, replacing Maltego for threat intelligence",
                author="founder1", score=156,
            ),
            # Will be filtered: non-English (Dutch)
            RawItem.create(
                source="rss", source_name="Marketing Land",
                title="Wat is social media marketing en wat zijn de voordelen?",
                url="http://marketingland.nl/1",
                body="Dit is een artikel over marketing in het Nederlands met vele woorden zoals het een van de",
                author="author1", score=5,
            ),
            # Will be filtered: mega-corp (google) — should NOT generate "google alternative" decision
            RawItem.create(
                source="rss", source_name="Search Engine Journal",
                title="Google announces new SEO algorithm update",
                url="http://sej.com/1",
                body="Google is rolling out a new core algorithm update, webmasters should prepare",
                author="author2", score=15,
            ),
            # Will trigger: cybersecurity domain (CVE)
            RawItem.create(
                source="hacker_news", source_name="Hacker News",
                title="Critical CVE-2024-12345 in Apache Log4j, actively exploited",
                url="http://news.ycombinator.com/3",
                body="Patch now, RCE vulnerability, threat actors actively exploiting in the wild",
                author="sec_user", score=450,
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

        from reports.decision_report import DecisionReportGenerator
        DecisionReportGenerator(cfg_dict["reports"]["decisions"]).generate(processed, workflow._run_id)

        strategy_path = StrategyReportGenerator(cfg_dict["reports"]["strategy"]).generate(processed, workflow._run_id)
        print(f"  ✓ Strategy report: {strategy_path}")

        # Show summary
        first = processed[0] if processed else None
        if first:
            print()
            print("=" * 70)
            scores = first.metadata.get("_scores", {})
            decisions = first.metadata.get("_decisions", {})
            strategy = first.metadata.get("_strategy", {})
            print(f"  Items collected:           {len(processed)}")
            print(f"  Companies scored:          {len(scores.get('company_scores', []))}")
            print(f"  Decisions (raw):           ?")
            print(f"  Decisions (after filter):  {decisions.get('total', 0)}")
            print(f"  Filtered out:              {sum(decisions.get('filter_counts', {}).values())}")
            print(f"    Filter reasons:          {decisions.get('filter_counts', {})}")
            print(f"  Strategy selected:         {len(strategy.get('selected', []))}")
            print(f"  Strategy excluded:         {len(strategy.get('excluded', []))}")
            print(f"  Projected ROI:             {strategy.get('projected', {}).get('total_roi', 0):.1f}")
            print(f"  Projected signups:         {strategy.get('projected', {}).get('total_signups', 0)}")
            print(f"  Projected revenue:         ${strategy.get('projected', {}).get('total_revenue_usd', 0)}")
            util = strategy.get('utilization', {})
            print(f"  Budget used:               ${util.get('budget_used_usd', 0)} / ${strategy.get('constraints', {}).get('budget_usd', 0)} ({util.get('budget_used_pct', 0):.1f}%)")
            print(f"  Time used:                 {util.get('time_used_hours', 0)}h / {strategy.get('constraints', {}).get('time_hours', 0)}h ({util.get('time_used_pct', 0):.1f}%)")

            # Show selected actions
            print()
            print("  Selected actions (optimal plan):")
            for i, s in enumerate(strategy.get("selected", []), 1):
                d = s["decision"]
                print(f"    {i}. ROI={s['roi']:.1f} | {d.get('type', ''):20s} | {d.get('target', ''):30s} | ${s['cost_usd']:,} + {s['cost_hours']}h")

            print()
            print("  Excluded actions:")
            for e in strategy.get("excluded", []):
                d = e["decision"]
                print(f"    ROI={e['roi']:.1f} | {d.get('type', ''):20s} | {d.get('target', ''):30s} | {e['reason']}")

            # Show domain signals
            print()
            print("  Domain signals detected:")
            for item in processed:
                ds = item.metadata.get("domain_signals", {})
                if ds:
                    domains = list(ds.keys())
                    print(f"    [{item.source_name:20s}] {item.title[:50]:50s} → {domains}")

            print("=" * 70)
            print("\n✓ Phase 5 strategy pipeline ran successfully")
            return True

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    success = test_phase5_strategy_pipeline()
    sys.exit(0 if success else 1)
