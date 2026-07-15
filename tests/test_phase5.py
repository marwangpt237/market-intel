"""Unit tests for Phase 5 modules: SourceAuthority, FalsePositiveFilter,
StrategyEngine, Domain modules."""
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.models import RawItem, ProcessedItem
from processors.source_authority import SourceAuthorityProcessor
from processors.false_positive_filter import FalsePositiveFilter
from processors.strategy_engine import StrategyEngine
from processors.domain_processor import DomainProcessor
from processors.domain.saas import SaaSDomainModule
from processors.domain.cybersecurity import CybersecurityDomainModule
from processors.domain.ecommerce import EcommerceDomainModule


def make_item(title: str, url: str, body: str = "", source: str = "test", source_name: str = "Test", score: int = 0) -> ProcessedItem:
    raw = RawItem.create(source=source, source_name=source_name, title=title, url=url, body=body, score=score)
    return ProcessedItem.from_raw(raw)


# ─── Source Authority ──────────────────────────────────────────────────

def test_source_authority_assigns_higher_score_to_hn():
    hn_item = make_item("Show HN: New tool", "http://hn.com/1", source="hacker_news", source_name="Hacker News", score=200)
    blog_item = make_item("Random blog post", "http://blog.com/1", source="rss", source_name="Unknown Blog", score=0)
    processor = SourceAuthorityProcessor({"min_authority": 0})
    result = processor.process([hn_item, blog_item])
    hn_auth = result[0].metadata["authority_score"]
    blog_auth = result[1].metadata["authority_score"]
    assert hn_auth > blog_auth, f"HN ({hn_auth}) should have higher authority than random blog ({blog_auth})"


def test_source_authority_drops_low_quality_items():
    spam = make_item("Buy cheap cialis online casino", "http://spam.com", body="affiliate link casino porn pharma")
    good = make_item("Discussion: SaaS pricing models", "http://hn.com", source="hacker_news", source_name="Hacker News", score=150)
    processor = SourceAuthorityProcessor({"min_authority": 30})
    result = processor.process([spam, good])
    assert len(result) == 1, f"Expected 1 item kept, got {len(result)}"
    assert result[0].title == "Discussion: SaaS pricing models"


def test_source_authority_demotes_non_english():
    dutch = make_item("Wat is social media marketing en wat zijn de voordelen?", "http://dutch.com",
                       source="rss", source_name="Marketing Land",
                       body="Dit is een artikel over marketing in het Nederlands met veel Nederlandse woorden zoals het een van de")
    english = make_item("What is social media marketing and its benefits?", "http://english.com",
                         source="rss", source_name="Marketing Land",
                         body="This is an article about marketing in English with many English words")
    processor = SourceAuthorityProcessor({"min_authority": 0, "non_english_penalty": 50})
    result = processor.process([dutch, english])
    dutch_auth = result[0].metadata["authority_score"]
    english_auth = result[1].metadata["authority_score"]
    assert dutch_auth < english_auth, f"Dutch ({dutch_auth}) should be demoted vs English ({english_auth})"
    assert (english_auth - dutch_auth) >= 30, f"Penalty should be significant (got delta {english_auth - dutch_auth})"


# ─── False Positive Filter ─────────────────────────────────────────────

def test_false_positive_filter_removes_mega_corp_targets():
    items = [make_item("test", "http://1.com")]
    items[0].metadata["_decisions"] = {
        "decisions": [
            {"id": "d1", "type": "launch_campaign", "priority": "P1", "target": "google",
             "rationale": "opportunity=80/100", "expected_impact": "medium",
             "suggested_action": "Build google alternative",
             "evidence": [{"item_id": "x", "title": "t", "url": "u", "source": "Reddit"},
                          {"item_id": "y", "title": "t", "url": "u", "source": "HN"}]},
            {"id": "d2", "type": "launch_campaign", "priority": "P1", "target": "hubspot",
             "rationale": "opportunity=70/100", "expected_impact": "medium",
             "suggested_action": "Build hubspot alternative",
             "evidence": [{"item_id": "x", "title": "t", "url": "u", "source": "Reddit"},
                          {"item_id": "y", "title": "t", "url": "u", "source": "HN"}]},
        ],
        "total": 2,
        "by_priority": {"P0": 0, "P1": 2, "P2": 0, "P3": 0},
        "by_type": {"launch_campaign": 2},
    }
    # Add authority scores so filter doesn't drop hubspot for low_authority
    for item in items:
        item.metadata["authority_score"] = 70

    processor = FalsePositiveFilter()
    result = processor.process(items)

    decisions = result[0].metadata["_decisions"]
    targets = [d["target"] for d in decisions["decisions"]]
    assert "google" not in targets, "Google should be filtered as mega_corp"
    assert "hubspot" in targets, "HubSpot should be kept (it's in the allowlist)"
    # Filter log should record mega_corp
    assert decisions["filter_counts"].get("mega_corp", 0) >= 1


def test_false_positive_filter_removes_generic_terms():
    items = [make_item("test", "http://1.com")]
    items[0].metadata["authority_score"] = 70
    items[0].metadata["_decisions"] = {
        "decisions": [
            {"id": "d1", "type": "write_content", "priority": "P2", "target": "marketing",
             "rationale": "trend=80/100 trend=hot", "expected_impact": "medium",
             "suggested_action": "Write about marketing",
             "evidence": [{"item_id": "x", "title": "t", "url": "u", "source": "Reddit"},
                          {"item_id": "y", "title": "t", "url": "u", "source": "HN"},
                          {"item_id": "z", "title": "t", "url": "u", "source": "RSS"}]},
        ],
        "total": 1, "by_priority": {}, "by_type": {},
    }
    processor = FalsePositiveFilter()
    result = processor.process(items)
    decisions = result[0].metadata["_decisions"]
    assert len(decisions["decisions"]) == 0
    assert decisions["filter_counts"].get("generic_term", 0) == 1


def test_false_positive_filter_removes_weak_evidence():
    items = [make_item("test", "http://1.com")]
    items[0].metadata["authority_score"] = 70
    items[0].metadata["_decisions"] = {
        "decisions": [
            {"id": "d1", "type": "launch_campaign", "priority": "P1", "target": "mailchimp",
             "rationale": "opportunity=50/100", "expected_impact": "medium",
             "suggested_action": "Build mailchimp alternative",
             "evidence": [{"item_id": "x", "title": "t", "url": "u", "source": "Reddit"}]},  # only 1 evidence
        ],
        "total": 1, "by_priority": {}, "by_type": {},
    }
    processor = FalsePositiveFilter({"min_evidence_count": 2})
    result = processor.process(items)
    decisions = result[0].metadata["_decisions"]
    assert len(decisions["decisions"]) == 0
    assert "weak_evidence" in decisions["filter_counts"]


def test_false_positive_filter_dedupes_same_target():
    items = [make_item("test", "http://1.com")]
    items[0].metadata["authority_score"] = 70
    items[0].metadata["_decisions"] = {
        "decisions": [
            {"id": "d1", "type": "launch_campaign", "priority": "P1", "target": "hubspot",
             "rationale": "opportunity=70/100", "expected_impact": "high",
             "suggested_action": "a1",
             "evidence": [{"item_id": "x", "title": "t", "url": "u", "source": "Reddit"},
                          {"item_id": "y", "title": "t", "url": "u", "source": "HN"}]},
            {"id": "d2", "type": "write_content", "priority": "P2", "target": "hubspot",
             "rationale": "opportunity=50/100", "expected_impact": "medium",
             "suggested_action": "a2",
             "evidence": [{"item_id": "x", "title": "t", "url": "u", "source": "Reddit"},
                          {"item_id": "y", "title": "t", "url": "u", "source": "HN"}]},
        ],
        "total": 2, "by_priority": {}, "by_type": {},
    }
    processor = FalsePositiveFilter()
    result = processor.process(items)
    decisions = result[0].metadata["_decisions"]
    assert len(decisions["decisions"]) == 1
    # Should keep the higher-priority one (P1 launch_campaign)
    assert decisions["decisions"][0]["priority"] == "P1"
    assert decisions["filter_counts"].get("duplicate_target", 0) == 1


# ─── Strategy Engine ───────────────────────────────────────────────────

def test_strategy_engine_selects_within_budget():
    items = [make_item("test", "http://1.com")]
    items[0].metadata["_decisions"] = {
        "decisions": [
            # Cheap action: write_content (~$100-300, 4-8h)
            {"id": "d1", "type": "write_content", "priority": "P1", "target": "ai-seo",
             "rationale": "trend=80/100 trend=hot opportunity=60/100", "expected_impact": "medium",
             "suggested_action": "Write article",
             "evidence": [{"item_id": "x", "title": "t", "url": "u", "source": "Reddit"}]},
            # Expensive action: build_feature (~$5k+, 80h+)
            {"id": "d2", "type": "build_feature", "priority": "P0", "target": "hubspot",
             "rationale": "opportunity=90/100", "expected_impact": "high",
             "suggested_action": "Build alternative",
             "evidence": [{"item_id": "x", "title": "t", "url": "u", "source": "Reddit"}]},
        ],
        "total": 2, "by_priority": {}, "by_type": {},
    }

    # Tight budget: $500, 20h — only the cheap action fits
    engine = StrategyEngine({"budget_usd": 500, "time_hours": 20})
    result = engine.process(items)

    strategy = result[0].metadata["_strategy"]
    selected_types = [s["decision"]["type"] for s in strategy["selected"]]
    excluded_types = [e["decision"]["type"] for e in strategy["excluded"]]
    assert "write_content" in selected_types
    assert "build_feature" in excluded_types
    assert strategy["utilization"]["actions_selected"] == 1


def test_strategy_engine_computes_roi():
    items = [make_item("test", "http://1.com")]
    items[0].metadata["_decisions"] = {
        "decisions": [
            {"id": "d1", "type": "write_content", "priority": "P1", "target": "ai-seo",
             "rationale": "opportunity=80/100 trend=hot", "expected_impact": "high",
             "suggested_action": "Write",
             "evidence": []},
        ],
        "total": 1, "by_priority": {}, "by_type": {},
    }

    engine = StrategyEngine({"budget_usd": 1000, "time_hours": 40})
    result = engine.process(items)

    strategy = result[0].metadata["_strategy"]
    assert len(strategy["selected"]) == 1
    s = strategy["selected"][0]
    assert 0 <= s["roi"] <= 100
    assert s["cost_usd"] > 0
    assert s["cost_hours"] > 0
    assert s["projected_signups"] >= 0


def test_strategy_engine_projects_totals():
    items = [make_item("test", "http://1.com")]
    items[0].metadata["_decisions"] = {
        "decisions": [
            {"id": "d1", "type": "write_content", "priority": "P1", "target": "topic1",
             "rationale": "opportunity=70/100 trend=hot", "expected_impact": "high",
             "suggested_action": "Write",
             "evidence": []},
            {"id": "d2", "type": "reach_out", "priority": "P1", "target": "hubspot",
             "rationale": "opportunity=60/100", "expected_impact": "medium",
             "suggested_action": "Email",
             "evidence": []},
        ],
        "total": 2, "by_priority": {}, "by_type": {},
    }

    engine = StrategyEngine({"budget_usd": 1000, "time_hours": 40})
    result = engine.process(items)

    strategy = result[0].metadata["_strategy"]
    projected = strategy["projected"]
    assert projected["total_roi"] > 0
    assert projected["total_signups"] >= 0
    assert projected["total_revenue_usd"] >= 0


def test_strategy_engine_utilization_under_constraints():
    """Verify that the engine never exceeds budget or time."""
    items = [make_item("test", "http://1.com")]
    decisions = []
    for i in range(10):
        decisions.append({
            "id": f"d{i}", "type": "write_content", "priority": "P1", "target": f"topic{i}",
            "rationale": "opportunity=70/100", "expected_impact": "medium",
            "suggested_action": "Write", "evidence": []
        })
    items[0].metadata["_decisions"] = {"decisions": decisions, "total": 10, "by_priority": {}, "by_type": {}}

    # Budget: $500, Time: 20h — should fill until exhausted
    engine = StrategyEngine({"budget_usd": 500, "time_hours": 20})
    result = engine.process(items)

    strategy = result[0].metadata["_strategy"]
    util = strategy["utilization"]
    assert util["budget_used_usd"] <= 500, f"Budget exceeded: {util['budget_used_usd']}"
    assert util["time_used_hours"] <= 20, f"Time exceeded: {util['time_used_hours']}"
    assert util["actions_selected"] < 10, "Should not have selected all 10 — constraints should bind"


# ─── Domain Modules ────────────────────────────────────────────────────

def test_saas_domain_detects_pricing_complaint():
    item = make_item("HubSpot pricing is insane", "http://1.com", body="Looking for cheaper alternative, need a different tool")
    module = SaaSDomainModule()
    signals = module.extract(item)
    assert "pricing_complaint" in signals["signals"]
    assert "alternative_seeking" in signals["signals"]
    assert signals["severity"] in ("high", "medium")


def test_saas_domain_detects_churn_signal():
    item = make_item("Switching from Mailchimp", "http://1.com", body="Cancelling my subscription, moving away to alternative, dropping them")
    module = SaaSDomainModule()
    signals = module.extract(item)
    assert "churn_mention" in signals["signals"]
    assert signals["severity"] in ("high", "medium")


def test_saas_domain_detects_feature_request():
    item = make_item("Wish Notion had better calendar", "http://1.com", body="I would pay for a native calendar integration")
    module = SaaSDomainModule()
    signals = module.extract(item)
    assert "feature_request" in signals["signals"]
    # 'calendar integration' should match the 'integration' pattern
    assert "integration_request" in signals["signals"]


def test_saas_domain_extracts_pricing_entities():
    item = make_item("SEMrush costs $99/month", "http://1.com", body="Their pricing is $99/mo for the basic tier, $249/year for premium")
    module = SaaSDomainModule()
    signals = module.extract(item)
    assert "mentioned_prices" in signals["entities"]
    assert 99.0 in signals["entities"]["mentioned_prices"]


def test_cybersecurity_domain_detects_cve():
    item = make_item("Critical RCE found in Apache", "http://1.com", body="CVE-2024-12345 is actively exploited, patch now")
    module = CybersecurityDomainModule()
    signals = module.extract(item)
    assert "cve_mention" in signals["signals"]
    assert "vulnerability_rce" in signals["signals"]
    assert "patch_urgency" in signals["signals"]
    assert "CVE-2024-12345" in signals["entities"].get("cves", [])
    assert signals["severity"] == "high"


def test_cybersecurity_domain_detects_compliance():
    item = make_item("GDPR compliance for SaaS", "http://1.com", body="Need SOC2 and HIPAA compliance for our healthcare app")
    module = CybersecurityDomainModule()
    signals = module.extract(item)
    assert "compliance_gdpr" in signals["signals"]
    assert "compliance_soc2" in signals["signals"]
    assert "compliance_hipaa" in signals["signals"]
    assert set(["GDPR", "SOC2", "HIPAA"]).issubset(set(signals["entities"].get("compliance_frameworks", [])))


def test_ecommerce_domain_detects_shipping_complaint():
    item = make_item("Slow shipping ruined my experience", "http://1.com", body="Never arrived, return denied, asking for refund")
    module = EcommerceDomainModule()
    signals = module.extract(item)
    assert "shipping_complaint" in signals["signals"]
    assert "return_issue" in signals["signals"]
    assert signals["severity"] == "high"


def test_ecommerce_domain_detects_inventory_demand():
    item = make_item("Viral product sold out everywhere", "http://1.com", body="Can't find it on amazon or etsy, out of stock")
    module = EcommerceDomainModule()
    signals = module.extract(item)
    assert "inventory_demand" in signals["signals"]
    assert "amazon_mention" in signals["signals"]
    assert "etsy_mention" in signals["signals"]
    assert "amazon" in signals["entities"].get("platforms", [])


def test_domain_processor_runs_all_modules():
    items = [
        make_item("HubSpot too expensive", "http://1.com", body="Need cheaper alternative"),
        make_item("CVE-2024-12345 critical", "http://2.com", body="Actively exploited, patch now"),
        make_item("Slow shipping complaint", "http://3.com", body="Never arrived, out of stock"),
    ]
    processor = DomainProcessor({})
    result = processor.process(items)

    # Each item should have at least one domain tag
    assert "domain_signals" in result[0].metadata
    assert "saas" in result[0].metadata["domain_signals"]
    assert "cybersecurity" in result[1].metadata["domain_signals"]
    assert "ecommerce" in result[2].metadata["domain_signals"]


# ─── End-to-end: Score → Decide → Filter → Strategy ───────────────────

def test_phase5_end_to_end_pipeline():
    """Full Phase 5 pipeline: scores → decisions → filter → strategy."""
    items = [
        make_item("HubSpot pricing is insane", "http://1.com", body="Need cheaper alternative, switching from HubSpot",
                  source="hacker_news", source_name="Hacker News", score=150),
        make_item("Show HN: open-source HubSpot alternative", "http://2.com", body="Free CRM with similar features",
                  source="hacker_news", source_name="Hacker News", score=80),
        make_item("Google SEO update analysis", "http://3.com", body="Google announced new algorithm",
                  source="rss", source_name="Search Engine Journal", score=20),
    ]

    # Stage 1: Source authority (run first to set authority_score)
    sa = SourceAuthorityProcessor({"min_authority": 25})
    items = sa.process(items)
    assert all("authority_score" in i.metadata for i in items)

    # Stage 2: Domain processor
    dp = DomainProcessor({})
    items = dp.process(items)
    assert "domain_signals" in items[0].metadata
    assert "saas" in items[0].metadata["domain_signals"]

    # Stage 3: Attach scores + decisions (simulating earlier pipeline output)
    items[0].metadata["_scores"] = {
        "company_scores": [{
            "entity": "hubspot", "type": "company",
            "opportunity_score": 80, "threat_score": 40, "competitor_weakness_score": 70,
            "data": {"mentions": 5, "pain_points": 3, "buying_signals": 2, "pricing_complaints": 4,
                     "seeking_alternatives": 3, "positive_sentiment": 0, "negative_sentiment": 5},
        }],
        "topic_scores": [],
        "insights": [],
    }

    from processors.decision_engine import DecisionEngine
    items = DecisionEngine({"opportunity_high": 60, "weakness_high": 50}).process(items)
    decisions_before = items[0].metadata["_decisions"]["total"]
    assert decisions_before > 0

    # Stage 4: False positive filter
    items = FalsePositiveFilter().process(items)
    decisions_after = items[0].metadata["_decisions"]["total"]
    # HubSpot should still be there (allowlisted)
    targets = [d["target"] for d in items[0].metadata["_decisions"]["decisions"]]
    assert "hubspot" in targets

    # Stage 5: Strategy engine
    items = StrategyEngine({"budget_usd": 500, "time_hours": 20}).process(items)
    strategy = items[0].metadata["_strategy"]
    assert "selected" in strategy
    assert "excluded" in strategy
    assert "projected" in strategy
    assert strategy["constraints"]["budget_usd"] == 500
