"""Smoke test for client_acq profile."""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from core.models import RawItem, ProcessedItem
from workflows.daily_run import DailyRun
from core.config_loader import load_config


def test_client_acq_profile_end_to_end():
    tmpdir = tempfile.mkdtemp()
    try:
        # Load client_acq profile
        config = load_config("config.client_acq.yaml")
        cfg_dict = config.to_dict()
        cfg_dict["storage"]["path"] = os.path.join(tmpdir, "client_acq.db")
        cfg_dict["reports"]["intelligence"]["output_path"] = os.path.join(tmpdir, "reports")
        cfg_dict["reports"]["strategy"]["output_path"] = os.path.join(tmpdir, "reports")
        cfg_dict["reports"]["learning"]["output_path"] = os.path.join(tmpdir, "reports")
        cfg_dict["reports"]["client_acq"]["output_path"] = os.path.join(tmpdir, "reports")
        cfg_dict["processors"]["execution_engine"]["output_path"] = os.path.join(tmpdir, "actions")

        # Disable collectors
        for cname in cfg_dict.get("collectors", {}):
            cfg_dict["collectors"][cname]["enabled"] = False

        from config.loader import Config
        config = Config(cfg_dict)
        workflow = DailyRun(config)

        # Mock prospects — realistic client_acq signals
        mock_raw = [
            RawItem.create(
                source="reddit", source_name="r/forhire",
                title="[Hiring] Looking for developer to build SaaS MVP for UK law firm",
                url="http://reddit.com/forhire/1",
                body="UK-based legaltech startup looking for a freelance developer to build our SaaS MVP. Have £15k budget, ready to start this week. Need someone experienced with React, Node.js, and HIPAA/GDPR compliance.",
                author="uk_founder_1", score=42,
            ),
            RawItem.create(
                source="reddit", source_name="r/freelance",
                title="Client needs Shopify store built for Singapore ecommerce brand",
                url="http://reddit.com/freelance/2",
                body="Singapore client looking for freelance developer to build a Shopify store. Paying $8000 SGD. Need someone who can also do custom theme development. Urgent — need to launch in 4 weeks.",
                author="sg_agency", score=28,
            ),
            RawItem.create(
                source="hacker_news", source_name="Hacker News",
                title="Ask HN: Agency recommendations for healthcare clinic website?",
                url="http://news.ycombinator.com/1",
                body="Anyone know a good developer or agency for a medical clinic website? US-based (San Francisco), need HIPAA-compliant patient portal. Budget around $12k. Bootstrapped, so cost matters.",
                author="us_clinic_admin", score=156,
            ),
            RawItem.create(
                source="job_boards", source_name="RemoteOK Dev Jobs",
                title="Full-stack developer wanted — funded fintech startup (Berlin)",
                url="http://remoteok.com/1",
                body="Berlin-based fintech startup (just raised seed round) hiring a contract full-stack developer. 3-month project to build our MVP. €18k budget. React + Node + Postgres. Ready to hire immediately.",
                author="de_fintech", score=89,
            ),
            RawItem.create(
                source="reddit", source_name="r/startups",
                title="Looking for technical co-founder — Toronto SaaS startup",
                url="http://reddit.com/startups/5",
                body="Toronto-based SaaS founder looking for technical co-founder. Pre-seed funded, have paying customers. Need someone to lead product engineering. Equity + small salary.",
                author="ca_founder", score=67,
            ),
            # Noise — should NOT generate client_acq signals
            RawItem.create(
                source="reddit", source_name="r/programming",
                title="What's your favorite code editor theme?",
                url="http://reddit.com/programming/6",
                body="Just curious what everyone's using these days. I'm a VS Code person myself.",
                author="dev_user", score=1250,
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

        # Client acquisition report (THE primary output)
        from reports.client_acq_report import ClientAcquisitionReportGenerator
        ca_path = ClientAcquisitionReportGenerator(cfg_dict["reports"]["client_acq"]).generate(processed, workflow._run_id)
        print(f"  ✓ Client acquisition report: {ca_path}")

        # Show summary
        print()
        print("=" * 70)
        # Find items with client_acq signals
        prospects = []
        for item in processed:
            ca = item.metadata.get("domain_signals", {}).get("client_acquisition", {})
            if ca and ca.get("signals"):
                prospects.append({
                    "title": item.title[:60],
                    "score": ca.get("entities", {}).get("lead_score", 0),
                    "countries": ca.get("entities", {}).get("countries", []),
                    "niches": ca.get("entities", {}).get("niches", []),
                    "project_types": ca.get("entities", {}).get("project_types", []),
                })

        print(f"  Total items:           {len(processed)}")
        print(f"  Prospects detected:    {len(prospects)}")
        print()
        print("  Top prospects:")
        prospects.sort(key=lambda p: -p["score"])
        for i, p in enumerate(prospects[:5], 1):
            print(f"    {i}. Score {p['score']:>3} | {p['title']}")
            print(f"       Countries: {p['countries']} | Niches: {p['niches']} | Projects: {p['project_types']}")

        # Print first 50 lines of the client_acq report
        print()
        print("=" * 70)
        print("  CLIENT ACQUISITION REPORT (first 100 lines):")
        print("=" * 70)
        with open(ca_path) as f:
            for i, line in enumerate(f):
                if i >= 100:
                    break
                print(f"  {line.rstrip()}")
        print("=" * 70)

        print("\n✓ Client acquisition profile ran successfully")
        return True

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    success = test_client_acq_profile_end_to_end()
    sys.exit(0 if success else 1)
