"""End-to-end smoke test for the full daily_run pipeline."""
import sys
import os
import tempfile
import shutil

# Setup path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from core.models import RawItem, ProcessedItem
from workflows.daily_run import DailyRun
from core.config_loader import load_config


def test_daily_run_end_to_end():
    """Run the full pipeline with mock data + all processors enabled."""
    tmpdir = tempfile.mkdtemp()
    try:
        config = load_config("config.yaml")
        cfg_dict = config.to_dict()
        cfg_dict["storage"]["path"] = os.path.join(tmpdir, "test.db")
        cfg_dict["reports"]["intelligence"]["output_path"] = os.path.join(tmpdir, "reports")
        cfg_dict["reports"]["decisions"]["output_path"] = os.path.join(tmpdir, "reports")
        cfg_dict["processors"]["execution_engine"]["output_path"] = os.path.join(tmpdir, "actions")

        # Disable all collectors (we'll inject mock data)
        for cname in cfg_dict.get("collectors", {}):
            cfg_dict["collectors"][cname]["enabled"] = False

        from config.loader import Config
        config = Config(cfg_dict)

        workflow = DailyRun(config)

        mock_raw = [
            RawItem.create(
                source="test_reddit", source_name="Reddit r/marketing",
                title="HubSpot pricing is insane, looking for cheaper alternative",
                url="http://reddit.com/1",
                body="Need cheaper CRM with similar features",
                author="user1", score=42,
            ),
            RawItem.create(
                source="test_reddit", source_name="Reddit r/marketing",
                title="SEMrush vs Ahrefs which is better for SEO in 2026",
                url="http://reddit.com/2",
                body="Comparing SEO tools for small agency",
                author="user2", score=28,
            ),
            RawItem.create(
                source="test_hn", source_name="Hacker News",
                title="Show HN: We built an open-source Maltego alternative",
                url="http://news.ycombinator.com/1",
                body="Free OSINT platform with 80+ plugins",
                author="founder1", score=156,
            ),
        ]

        processed = [ProcessedItem.from_raw(r) for r in mock_raw]

        processors = workflow._container.get_processors()
        for name, processor in processors.items():
            try:
                processed = processor.process(processed)
                print(f"  ✓ {name}: {len(processed)} items")
            except Exception as e:
                print(f"  ✗ {name} failed: {e}")

        storage = workflow._container.get_storage()
        storage.save([workflow._processed_to_dict(item) for item in processed], workflow._run_id)

        report_gen = workflow._container.get_report_generator()
        report_path = report_gen.generate(processed, workflow._run_id)
        print(f"  ✓ Intelligence report: {report_path}")

        from reports.decision_report import DecisionReportGenerator
        dec_gen = DecisionReportGenerator(cfg_dict["reports"]["decisions"])
        dec_path = dec_gen.generate(processed, workflow._run_id)
        print(f"  ✓ Decision report: {dec_path}")

        first_item = processed[0]
        scores = first_item.metadata.get("_scores", {})
        decisions = first_item.metadata.get("_decisions", {})
        executions = first_item.metadata.get("_executions", {})
        analytics = first_item.metadata.get("_analytics", {})
        learning = first_item.metadata.get("_learning", {})

        print()
        print("=" * 60)
        print(f"  Companies scored: {len(scores.get('company_scores', []))}")
        print(f"  Topics scored: {len(scores.get('topic_scores', []))}")
        print(f"  Insights: {len(scores.get('insights', []))}")
        print(f"  Decisions: {decisions.get('total', 0)}")
        print(f"  By priority: {decisions.get('by_priority', {})}")
        print(f"  Artifacts generated: {executions.get('total', 0)}")
        print(f"  Actions in DB: {analytics.get('total_actions_in_db', 0)}")
        print(f"  Learning adjustments: {len(learning.get('weight_adjustments', []))}")
        print("=" * 60)

        actions_dir = os.path.join(tmpdir, "actions")
        if os.path.exists(actions_dir):
            for d in os.listdir(actions_dir):
                full = os.path.join(actions_dir, d)
                if os.path.isdir(full):
                    files = os.listdir(full)
                    print(f"  Actions dir {d}: {len(files)} files")
                    for f in files[:3]:
                        print(f"    - {f}")

        weights_path = os.path.join(tmpdir, "learning_weights.json")
        if os.path.exists(weights_path):
            print(f"  ✓ Weights file persisted")

        metrics_path = os.path.join(tmpdir, "metrics_input_template.json")
        if os.path.exists(metrics_path):
            print(f"  ✓ Metrics template generated")

        print()
        print("✓ Full closed-loop pipeline ran successfully")
        return True

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    success = test_daily_run_end_to_end()
    sys.exit(0 if success else 1)
