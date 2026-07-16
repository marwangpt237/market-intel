"""Unit tests for Client Acquisition module + report."""
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.models import RawItem, ProcessedItem
from processors.domain.client_acquisition import ClientAcquisitionModule
from processors.domain_processor import DomainProcessor
from reports.client_acq_report import ClientAcquisitionReportGenerator


def make_item(title: str, url: str, body: str = "", source: str = "reddit", source_name: str = "r/forhire") -> ProcessedItem:
    raw = RawItem.create(source=source, source_name=source_name, title=title, url=url, body=body)
    return ProcessedItem.from_raw(raw)


# ─── Client Acquisition Module ─────────────────────────────────────────

def test_detects_looking_for_developer():
    item = make_item("Looking for developer to build MVP", "http://1.com",
                     body="Need a developer for a SaaS MVP, have budget")
    module = ClientAcquisitionModule()
    result = module.extract(item)

    assert "looking_for_developer" in result["signals"]
    assert "need_mvp" in result["signals"]
    assert "has_budget" in result["signals"]
    assert result["severity"] in ("high", "medium")
    assert result["entities"]["lead_score"] > 20


def test_detects_hiring_freelance():
    item = make_item("Hiring freelance developer for Shopify store", "http://1.com",
                     body="Need someone to build our ecommerce store, paying $5000")
    module = ClientAcquisitionModule()
    result = module.extract(item)

    assert "hiring_freelance" in result["signals"]
    assert "need_ecommerce" in result["signals"]
    assert "has_budget" in result["signals"]
    assert 5000.0 in result["entities"]["budget_amounts"]


def test_detects_agency_recommendation():
    item = make_item("Agency recommendations for legal website?", "http://1.com",
                     body="Any good agencies for a law firm website redesign?")
    module = ClientAcquisitionModule()
    result = module.extract(item)

    assert "agency_recommendation" in result["signals"]
    assert "need_website" in result["signals"]
    assert "legal" in result["entities"]["niches"]


def test_detects_technical_cofounder():
    item = make_item("Looking for technical co-founder", "http://1.com",
                     body="Pre-seed funded startup seeking technical co-founder for SaaS product")
    module = ClientAcquisitionModule()
    result = module.extract(item)

    assert "technical_cofounder" in result["signals"]
    assert "funded" in result["signals"]
    assert "saas" in result["entities"]["niches"]
    assert "startup" in result["entities"]["niches"]


def test_detects_uk_country():
    item = make_item("Need a developer in London", "http://1.com",
                     body="UK-based startup looking for someone to build our SaaS MVP")
    module = ClientAcquisitionModule()
    result = module.extract(item)

    assert "UK" in result["entities"]["countries"]
    assert "saas" in result["entities"]["niches"]


def test_detects_usa_country():
    item = make_item("Looking for developer in San Francisco", "http://1.com",
                     body="Bay Area startup hiring, need someone to build MVP")
    module = ClientAcquisitionModule()
    result = module.extract(item)

    assert "USA" in result["entities"]["countries"]


def test_detects_multiple_countries():
    item = make_item("Remote — open to UK, Canada, Australia", "http://1.com",
                     body="Looking for developer, open to applicants from UK, Canada, or Australia")
    module = ClientAcquisitionModule()
    result = module.extract(item)

    countries = result["entities"]["countries"]
    assert "UK" in countries
    assert "Canada" in countries
    assert "Australia" in countries


def test_detects_niche_medical():
    item = make_item("Need website for medical clinic", "http://1.com",
                     body="Healthcare clinic looking for a developer, must be HIPAA compliant")
    module = ClientAcquisitionModule()
    result = module.extract(item)

    assert "medical" in result["entities"]["niches"]


def test_detects_project_type_mobile_app():
    item = make_item("Need an iOS app built", "http://1.com",
                     body="Looking for developer to build our mobile app, react native preferred")
    module = ClientAcquisitionModule()
    result = module.extract(item)

    assert "mobile_app" in result["entities"]["project_types"]


def test_detects_budget_amounts():
    item = make_item("Have $10k budget for website", "http://1.com",
                     body="Looking for developer, my budget is $10,000 for the full project")
    module = ClientAcquisitionModule()
    result = module.extract(item)

    assert "has_budget" in result["signals"]
    assert "budget_amount" in result["signals"]
    amounts = result["entities"]["budget_amounts"]
    assert any(9000 <= a <= 11000 for a in amounts), f"Expected ~10k in {amounts}"


def test_lead_score_increases_with_more_signals():
    # Low-intent item
    low_item = make_item("Random discussion about web dev", "http://1.com",
                          body="Just chatting about programming languages")
    # High-intent item
    high_item = make_item("Looking for developer, $20k budget, urgent", "http://2.com",
                            body="Need a SaaS MVP built this month, fully funded, ready to start ASAP")

    module = ClientAcquisitionModule()
    low_result = module.extract(low_item)
    high_result = module.extract(high_item)

    assert high_result["entities"]["lead_score"] > low_result["entities"]["lead_score"]
    assert high_result["entities"]["lead_score"] >= 40  # high severity
    assert low_result["entities"]["lead_score"] < 20   # low or none


def test_outreach_channel_mapping():
    # Reddit post → reddit_reply
    reddit_item = make_item("Looking for developer", "http://reddit.com/1",
                             source="reddit", source_name="r/forhire")
    # HN post → hn_reply
    hn_item = make_item("Looking for developer", "http://hn.com/1",
                         source="hacker_news", source_name="Hacker News")
    # Job board → job_board_apply
    job_item = make_item("Full-stack developer wanted", "http://remoteok.com/1",
                          source="job_boards", source_name="RemoteOK Dev Jobs")

    module = ClientAcquisitionModule()
    reddit_result = module.extract(reddit_item)
    hn_result = module.extract(hn_item)
    job_result = module.extract(job_item)

    assert reddit_result["entities"]["outreach_channel"] == "reddit_reply"
    assert hn_result["entities"]["outreach_channel"] == "hn_reply"
    assert job_result["entities"]["outreach_channel"] == "job_board_apply"


def test_no_signals_returns_empty():
    item = make_item("Beautiful sunset today", "http://1.com",
                     body="Just sharing a photo of the sunset")
    module = ClientAcquisitionModule()
    result = module.extract(item)

    assert result["signals"] == []
    assert result["severity"] == "none"
    assert result["entities"]["lead_score"] == 0


# ─── Domain Processor integration ──────────────────────────────────────

def test_domain_processor_runs_client_acq_when_enabled():
    items = [
        make_item("Looking for developer for SaaS MVP", "http://1.com",
                  body="UK startup, have $15k budget, ready to start"),
        make_item("Random unrelated post", "http://2.com", body="Just chatting"),
    ]
    processor = DomainProcessor({
        "saas": {"enabled": False},
        "cybersecurity": {"enabled": False},
        "ecommerce": {"enabled": False},
        "client_acquisition": {"enabled": True},
    })
    result = processor.process(items)

    # First item should have client_acquisition signals
    assert "domain_signals" in result[0].metadata
    assert "client_acquisition" in result[0].metadata["domain_signals"]
    ca_signals = result[0].metadata["domain_signals"]["client_acquisition"]
    assert ca_signals["entities"]["lead_score"] > 20
    assert "UK" in ca_signals["entities"]["countries"]
    assert "saas" in ca_signals["entities"]["niches"]


def test_domain_processor_skips_client_acq_when_disabled():
    items = [make_item("Looking for developer", "http://1.com")]
    processor = DomainProcessor({})  # default config — client_acq off
    result = processor.process(items)

    # Should NOT have client_acquisition signals (off by default)
    signals = result[0].metadata.get("domain_signals", {})
    assert "client_acquisition" not in signals


# ─── Client Acquisition Report ─────────────────────────────────────────

def test_client_acq_report_generates_with_prospects():
    tmpdir = tempfile.mkdtemp()
    try:
        items = [
            make_item("Looking for developer for SaaS MVP", "http://reddit.com/1",
                       body="UK startup, $15k budget, ready to start this week",
                       source="reddit", source_name="r/forhire"),
            make_item("Need website for law firm in London", "http://reddit.com/2",
                       body="Any agencies recommended for legal websites? UK based",
                       source="reddit", source_name="r/freelance"),
            make_item("Hiring full-stack dev for fintech app", "http://remoteok.com/1",
                       body="Singapore fintech, $8k budget, contract role",
                       source="job_boards", source_name="RemoteOK"),
        ]
        # Run domain processor to tag items
        processor = DomainProcessor({
            "saas": {"enabled": False},
            "cybersecurity": {"enabled": False},
            "ecommerce": {"enabled": False},
            "client_acquisition": {"enabled": True},
        })
        items = processor.process(items)

        # Generate report
        report_gen = ClientAcquisitionReportGenerator({
            "output_path": tmpdir,
            "top_prospects_count": 10,
            "top_countries_count": 5,
            "top_niches_count": 5,
        })
        report_path = report_gen.generate(items, "test_run_001")

        assert os.path.exists(report_path)
        content = open(report_path).read()

        # Should contain strategic recommendation
        assert "Strategic Recommendation" in content
        # Should contain prospects table
        assert "Top Prospects" in content
        # Should mention detected countries
        assert "UK" in content
        assert "Singapore" in content
        # Should mention detected niches
        assert "saas" in content.lower()
        assert "legal" in content.lower()
        assert "fintech" in content.lower()
        # Should contain ROI projection
        assert "ROI Projection" in content
        # Should contain LinkedIn content suggestions
        assert "LinkedIn Content" in content
        # Should contain Reddit threads section
        assert "Reddit Threads" in content
        # Should contain Job board gigs section
        assert "Job Board Gigs" in content

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_client_acq_report_handles_empty_prospects():
    """Report should not crash if no prospects detected."""
    tmpdir = tempfile.mkdtemp()
    try:
        items = [
            make_item("Random post about programming", "http://1.com", body="Just discussing"),
        ]
        # Run domain processor — no client_acq signals will match
        processor = DomainProcessor({
            "client_acquisition": {"enabled": True},
        })
        items = processor.process(items)

        report_gen = ClientAcquisitionReportGenerator({"output_path": tmpdir})
        report_path = report_gen.generate(items, "test_run_002")

        assert os.path.exists(report_path)
        content = open(report_path).read()
        assert "No high-intent prospects" in content
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ─── End-to-end: profile config + domain + report ──────────────────────

def test_client_acq_profile_loads():
    """Verify the client_acq config file loads and has client_acquisition enabled."""
    from core.config_loader import load_config
    config = load_config("config.client_acq.yaml")

    # Client acquisition domain should be enabled
    domain_cfg = config.processors.get("domain", {})
    assert domain_cfg.get("client_acquisition", {}).get("enabled") is True
    # Other domain modules should be disabled
    assert domain_cfg.get("saas", {}).get("enabled") is False

    # Client_acq report should be enabled
    assert config.reports.get("client_acq", {}).get("enabled") is True

    # Collectors should be tuned for client acquisition
    reddit_cfg = config.collectors.get("reddit", {})
    assert "forhire" in reddit_cfg.get("subreddits", [])
    assert "freelance" in reddit_cfg.get("subreddits", [])

    # Storage should be separate DB
    storage_path = config.storage.get("path", "")
    assert "client_acq" in storage_path


def test_main_py_resolves_client_acq_profile():
    """Verify main.py resolves the client_acq profile to the right config path."""
    from main import resolve_config_path

    # Explicit profile
    assert resolve_config_path("client_acq") == "config.client_acq.yaml"
    # Default
    assert resolve_config_path(None) == "config.yaml"
    assert resolve_config_path("default") == "config.yaml"
