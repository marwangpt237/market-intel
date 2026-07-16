"""Unit tests for Phase 8 — Evidence Validation Engine."""
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.models import RawItem, ProcessedItem
from validation.models import (
    Claim, Evidence, ValidationStatus, ClaimType,
    compute_claim_id, compute_expiration_date,
    CONFIDENCE_VERIFIED, CONFIDENCE_PROBABLE,
    CLAIM_FRESHNESS_DAYS, CONTRADICTION_TOLERANCE,
)
from validation.trust_layer import TrustLayer
from validation.claim_store import ClaimStore
from validation.evidence_validator import EvidenceValidator
from validation.claim_extractor import ClaimExtractor
from validation.decision_ledger import DecisionLedger, compute_decision_confidence
from validation.engine import ValidationEngine


def make_item(title: str, url: str, body: str = "", source: str = "test", source_name: str = "Test", score: int = 0) -> ProcessedItem:
    raw = RawItem.create(source=source, source_name=source_name, title=title, url=url, body=body, score=score)
    return ProcessedItem.from_raw(raw)


# ─── Models ────────────────────────────────────────────────────────────

def test_claim_id_is_stable():
    """Same entity + type + value → same ID."""
    id1 = compute_claim_id("product:backpack", "average_price", 4200)
    id2 = compute_claim_id("product:backpack", "average_price", 4200)
    id3 = compute_claim_id("product:backpack", "average_price", 4500)  # different value
    assert id1 == id2
    assert id1 != id3


def test_claim_id_format():
    cid = compute_claim_id("entity", "type", "value")
    assert cid.startswith("clm_")
    assert len(cid) == 16  # "clm_" + 12 hex chars


def test_claim_to_dict_roundtrip():
    claim = Claim(
        id="clm_test",
        entity="product:test",
        claim_type="average_price",
        value=4200,
        value_unit="DZD",
        confidence_score=0.75,
        validation_status="PROBABLE",
    )
    d = claim.to_dict()
    claim2 = Claim.from_dict(d)
    assert claim2.id == claim.id
    assert claim2.value == claim.value
    assert claim2.confidence_score == claim.confidence_score


def test_expiration_date_based_on_claim_type():
    """Different claim types have different freshness windows."""
    ramadan_expiry = compute_expiration_date("seasonal_signal")
    trend_expiry = compute_expiration_date("trend")
    assert ramadan_expiry != trend_expiry  # different windows
    # Trends expire faster (3 days) than seasonal (60 days)
    assert CLAIM_FRESHNESS_DAYS["trend"] < CLAIM_FRESHNESS_DAYS["seasonal_signal"]


def test_evidence_dataclass():
    ev = Evidence(
        source_id="aps.dz",
        source_type="rss",
        source_reliability=0.90,
        value=4200,
        supports=True,
        confidence=1.0,
    )
    d = ev.to_dict()
    assert d["source_id"] == "aps.dz"
    assert d["source_reliability"] == 0.90
    assert d["supports"] is True


# ─── Trust Layer ──────────────────────────────────────────────────────

def test_trust_layer_default_reliability_by_type():
    tl = TrustLayer()
    assert tl.get_reliability("unknown_id", "hacker_news") == 0.85
    assert tl.get_reliability("unknown_id", "rss") == 0.75
    assert tl.get_reliability("unknown_id", "reddit") == 0.65


def test_trust_layer_high_credibility_source_override():
    tl = TrustLayer()
    # aps.dz is high-credibility (0.90) — should override RSS default (0.75)
    rel = tl.get_reliability("aps.dz", "rss", "APS Algeria")
    assert rel == 0.90


def test_trust_layer_low_credibility_penalty():
    tl = TrustLayer()
    rel = tl.get_reliability("spam.com", "rss", "spam affiliate site")
    assert rel < 0.30


def test_trust_layer_is_reliable_enough():
    tl = TrustLayer({"min_evidence_reliability": 0.30})
    assert tl.is_reliable_enough(0.50) is True
    assert tl.is_reliable_enough(0.20) is False


def test_trust_layer_learned_reliability_override():
    tl = TrustLayer()
    tl.update_learned_reliability("custom_source", 0.92)
    assert tl.get_reliability("custom_source") == 0.92


def test_trust_layer_stats():
    tl = TrustLayer()
    stats = tl.get_stats()
    assert "total_sources_known" in stats
    assert "min_evidence_reliability" in stats
    assert stats["min_evidence_reliability"] == 0.30


# ─── Claim Store ───────────────────────────────────────────────────────

def test_claim_store_upsert_and_get():
    tmpdir = tempfile.mkdtemp()
    try:
        store = ClaimStore(os.path.join(tmpdir, "test.db"))
        claim = Claim(
            id="clm_test1",
            entity="product:backpack",
            claim_type="average_price",
            value=4200,
            value_unit="DZD",
            confidence_score=0.75,
            validation_status="PROBABLE",
        )
        is_new = store.upsert_claim(claim)
        assert is_new is True

        # Get it back
        retrieved = store.get_claim("clm_test1")
        assert retrieved is not None
        assert retrieved.value == 4200
        assert retrieved.confidence_score == 0.75

        # Upsert again — should not be new
        is_new = store.upsert_claim(claim)
        assert is_new is False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_claim_store_get_by_entity():
    tmpdir = tempfile.mkdtemp()
    try:
        store = ClaimStore(os.path.join(tmpdir, "test.db"))
        for val in [100, 200, 300]:
            store.upsert_claim(Claim(
                id=f"clm_{val}",
                entity="product:test",
                claim_type="average_price",
                value=val,
            ))
        # Different entity
        store.upsert_claim(Claim(
            id="clm_other",
            entity="product:other",
            claim_type="average_price",
            value=999,
        ))

        claims = store.get_claims_by_entity("product:test")
        assert len(claims) == 3
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_claim_store_get_by_status():
    tmpdir = tempfile.mkdtemp()
    try:
        store = ClaimStore(os.path.join(tmpdir, "test.db"))
        store.upsert_claim(Claim(id="c1", entity="e1", claim_type="t", value=1, validation_status="VERIFIED"))
        store.upsert_claim(Claim(id="c2", entity="e2", claim_type="t", value=2, validation_status="VERIFIED"))
        store.upsert_claim(Claim(id="c3", entity="e3", claim_type="t", value=3, validation_status="HYPOTHESIS"))

        verified = store.get_claims_by_status("VERIFIED")
        assert len(verified) == 2
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_claim_store_add_evidence():
    tmpdir = tempfile.mkdtemp()
    try:
        store = ClaimStore(os.path.join(tmpdir, "test.db"))
        store.upsert_claim(Claim(id="c1", entity="e", claim_type="t", value=1))
        ev = Evidence(source_id="s1", source_type="rss", source_reliability=0.8, value=1)
        store.add_evidence("c1", ev)
        evidence = store.get_evidence_for_claim("c1")
        assert len(evidence) == 1
        assert evidence[0]["source_id"] == "s1"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_claim_store_version_history():
    tmpdir = tempfile.mkdtemp()
    try:
        store = ClaimStore(os.path.join(tmpdir, "test.db"))
        store.upsert_claim(Claim(id="c1", entity="e", claim_type="t", value=1, validation_status="HYPOTHESIS"))
        store.add_version_history("c1", "HYPOTHESIS", "PROBABLE", 0.3, 0.6, "Got more sources")
        history = store.get_version_history("c1")
        assert len(history) == 1
        assert history[0]["old_status"] == "HYPOTHESIS"
        assert history[0]["new_status"] == "PROBABLE"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_claim_store_stats():
    tmpdir = tempfile.mkdtemp()
    try:
        store = ClaimStore(os.path.join(tmpdir, "test.db"))
        store.upsert_claim(Claim(id="c1", entity="e", claim_type="t", value=1, validation_status="VERIFIED", confidence_score=0.8))
        store.upsert_claim(Claim(id="c2", entity="e", claim_type="t", value=2, validation_status="HYPOTHESIS", confidence_score=0.2))
        store.add_evidence("c1", Evidence(source_id="s", source_type="rss", source_reliability=0.8, value=1))

        stats = store.get_stats()
        assert stats["total_claims"] == 2
        assert stats["by_status"]["VERIFIED"] == 1
        assert stats["by_status"]["HYPOTHESIS"] == 1
        assert stats["total_evidence_pieces"] == 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ─── Evidence Validator ────────────────────────────────────────────────

def test_validator_single_source_becomes_hypothesis():
    tmpdir = tempfile.mkdtemp()
    try:
        store = ClaimStore(os.path.join(tmpdir, "test.db"))
        tl = TrustLayer()
        validator = EvidenceValidator(store, tl)

        claim = Claim(
            id="clm_test",
            entity="product:test",
            claim_type="average_price",
            value=4200,
        )
        ev = [Evidence(source_id="s1", source_type="rss", source_reliability=0.75, value=4200, supports=True)]
        result = validator.validate_claim(claim, ev)

        assert result.validation_status == "HYPOTHESIS"
        assert 0 < result.confidence_score <= 1.0
        assert len(result.supporting_evidence) == 1
        assert len(result.contradicting_evidence) == 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_validator_two_sources_becomes_probable():
    tmpdir = tempfile.mkdtemp()
    try:
        store = ClaimStore(os.path.join(tmpdir, "test.db"))
        tl = TrustLayer()
        validator = EvidenceValidator(store, tl)

        claim = Claim(
            id="clm_test",
            entity="product:test",
            claim_type="average_price",
            value=4200,
        )
        ev = [
            Evidence(source_id="s1", source_type="rss", source_reliability=0.80, value=4200, supports=True),
            Evidence(source_id="s2", source_type="rss", source_reliability=0.75, value=4200, supports=True),
        ]
        result = validator.validate_claim(claim, ev)

        assert result.validation_status == "PROBABLE"
        assert result.confidence_score >= 0.40
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_validator_three_sources_becomes_verified():
    tmpdir = tempfile.mkdtemp()
    try:
        store = ClaimStore(os.path.join(tmpdir, "test.db"))
        tl = TrustLayer()
        validator = EvidenceValidator(store, tl)

        claim = Claim(
            id="clm_test",
            entity="product:test",
            claim_type="average_price",
            value=4200,
        )
        ev = [
            Evidence(source_id="s1", source_type="rss", source_reliability=0.85, value=4200, supports=True),
            Evidence(source_id="s2", source_type="rss", source_reliability=0.80, value=4200, supports=True),
            Evidence(source_id="s3", source_type="rss", source_reliability=0.75, value=4200, supports=True),
        ]
        result = validator.validate_claim(claim, ev)

        assert result.validation_status == "VERIFIED"
        assert result.confidence_score >= 0.70
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_validator_contradicting_evidence_creates_conflicted():
    tmpdir = tempfile.mkdtemp()
    try:
        store = ClaimStore(os.path.join(tmpdir, "test.db"))
        tl = TrustLayer()
        validator = EvidenceValidator(store, tl)

        claim = Claim(
            id="clm_test",
            entity="product:test",
            claim_type="average_price",
            value=4200,
        )
        ev = [
            Evidence(source_id="s1", source_type="rss", source_reliability=0.85, value=4200, supports=True),
            Evidence(source_id="s2", source_type="rss", source_reliability=0.80, value=9000, supports=False),  # 9000 vs 4200 = >30% diff
        ]
        result = validator.validate_claim(claim, ev)

        assert result.validation_status == "CONFLICTED"
        assert len(result.contradicting_evidence) == 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_validator_low_reliability_sources_dont_count():
    """Sources with reliability < 0.30 don't count toward min_sources."""
    tmpdir = tempfile.mkdtemp()
    try:
        store = ClaimStore(os.path.join(tmpdir, "test.db"))
        tl = TrustLayer()
        validator = EvidenceValidator(store, tl)

        claim = Claim(
            id="clm_test",
            entity="product:test",
            claim_type="average_price",
            value=4200,
        )
        ev = [
            Evidence(source_id="spam1", source_type="rss", source_reliability=0.20, value=4200, supports=True),
            Evidence(source_id="spam2", source_type="rss", source_reliability=0.15, value=4200, supports=True),
        ]
        result = validator.validate_claim(claim, ev)

        # Even with 2 sources, both have low reliability → HYPOTHESIS not PROBABLE
        assert result.validation_status == "HYPOTHESIS"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_validator_missing_evidence_request_emitted():
    """When confidence is low, validator should emit a missing-evidence request."""
    tmpdir = tempfile.mkdtemp()
    try:
        store = ClaimStore(os.path.join(tmpdir, "test.db"))
        tl = TrustLayer()
        validator = EvidenceValidator(store, tl)

        claim = Claim(
            id="clm_test",
            entity="product:test",
            claim_type="average_price",
            value=4200,
        )
        ev = [Evidence(source_id="s1", source_type="rss", source_reliability=0.50, value=4200, supports=True)]
        validator.validate_claim(claim, ev)

        missing = validator.get_missing_evidence_requests()
        assert len(missing) >= 1
        assert missing[0]["claim_id"] == "clm_test"
        assert "needed_sources" in missing[0]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_validator_persists_claim_and_evidence():
    tmpdir = tempfile.mkdtemp()
    try:
        store = ClaimStore(os.path.join(tmpdir, "test.db"))
        tl = TrustLayer()
        validator = EvidenceValidator(store, tl)

        claim = Claim(
            id="clm_test",
            entity="product:test",
            claim_type="average_price",
            value=4200,
        )
        ev = [
            Evidence(source_id="s1", source_type="rss", source_reliability=0.80, value=4200, supports=True),
            Evidence(source_id="s2", source_type="rss", source_reliability=0.75, value=4200, supports=True),
        ]
        validator.validate_claim(claim, ev)

        # Verify claim was persisted
        retrieved = store.get_claim("clm_test")
        assert retrieved is not None
        assert retrieved.validation_status == "PROBABLE"

        # Verify evidence was persisted
        evidence = store.get_evidence_for_claim("clm_test")
        assert len(evidence) == 2
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_validator_version_history_recorded():
    tmpdir = tempfile.mkdtemp()
    try:
        store = ClaimStore(os.path.join(tmpdir, "test.db"))
        tl = TrustLayer()
        validator = EvidenceValidator(store, tl)

        claim = Claim(
            id="clm_test",
            entity="product:test",
            claim_type="average_price",
            value=4200,
        )
        # First validation: single source → HYPOTHESIS
        ev1 = [Evidence(source_id="s1", source_type="rss", source_reliability=0.80, value=4200, supports=True)]
        validator.validate_claim(claim, ev1)

        # Second validation: add another source → PROBABLE
        ev2 = [
            Evidence(source_id="s1", source_type="rss", source_reliability=0.80, value=4200, supports=True),
            Evidence(source_id="s2", source_type="rss", source_reliability=0.75, value=4200, supports=True),
        ]
        validator.validate_claim(claim, ev2)

        # Version history should show the transition
        history = store.get_version_history("clm_test")
        assert len(history) >= 1
        # Most recent should show PROBABLE
        assert history[0]["new_status"] == "PROBABLE"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ─── Claim Extractor ───────────────────────────────────────────────────

def test_claim_extractor_extracts_algeria_products():
    item = make_item("Sac à dos 3500 DA Alger", "http://1.com", source="rss", source_name="APS Algeria")
    item.metadata["algeria"] = {
        "products": [{"name": "sac", "category": "bags", "price_dzd": 3500}],
        "wilayas": ["DZ-16"],
        "wilaya_names": ["Alger"],
    }

    tl = TrustLayer()
    extractor = ClaimExtractor(tl)
    claims = extractor.extract_from_items([item])

    # Should extract at least:
    # - 1 average_price claim for product:bags
    # - 1 wilaya_demand claim for wilaya:Alger
    claim_types = [(c.entity, c.claim_type) for c, _ in claims]
    assert any("product:bags" in entity and "average_price" in ctype for entity, ctype in claim_types)
    assert any("wilaya:Alger" in entity and "wilaya_demand" in ctype for entity, ctype in claim_types)


def test_claim_extractor_extracts_generic_claims():
    item = make_item("HubSpot too expensive", "http://1.com", source="hacker_news", source_name="Hacker News")
    item.metadata["entities"] = {"companies": ["hubspot"]}
    item.metadata["pain_points"] = [{"category": "pricing", "severity": "high", "text": "expensive"}]
    item.metadata["buying_signals"] = [{"type": "budget", "confidence": 0.8}]

    tl = TrustLayer()
    extractor = ClaimExtractor(tl)
    claims = extractor.extract_from_items([item])

    claim_types = [(c.entity, c.claim_type) for c, _ in claims]
    assert any("company:hubspot" in entity and "entity_mention" in ctype for entity, ctype in claim_types)
    assert any("pain_point:pricing" in entity and "pain_point" in ctype for entity, ctype in claim_types)
    assert any("buying_signal:budget" in entity and "buying_signal" in ctype for entity, ctype in claim_types)


def test_claim_extractor_evidence_includes_source_reliability():
    item = make_item("Test", "http://1.com", source="rss", source_name="APS Algeria")
    item.metadata["algeria"] = {
        "products": [{"name": "x", "category": "test", "price_dzd": 100}],
    }

    tl = TrustLayer()
    extractor = ClaimExtractor(tl)
    claims = extractor.extract_from_items([item])

    assert len(claims) >= 1
    _, evidence_list = claims[0]
    assert len(evidence_list) >= 1
    # APS Algeria has reliability 0.90
    assert evidence_list[0].source_reliability == 0.90


# ─── Decision Ledger ───────────────────────────────────────────────────

def test_decision_ledger_records_decision():
    tmpdir = tempfile.mkdtemp()
    try:
        ledger = DecisionLedger(os.path.join(tmpdir, "test.db"))
        ledger.record_decision(
            decision_id="dec_001",
            decision_type="launch_campaign",
            target="hubspot",
            priority="P1",
            suggested_action="Build alternative",
            claim_ids=["clm_001", "clm_002"],
            claim_confidences=[
                {"claim_id": "clm_001", "confidence": 0.8, "status": "VERIFIED"},
                {"claim_id": "clm_002", "confidence": 0.6, "status": "PROBABLE"},
            ],
            decision_confidence=0.72,
            warnings=[],
        )

        retrieved = ledger.get_decision("dec_001")
        assert retrieved is not None
        assert retrieved["decision_type"] == "launch_campaign"
        assert retrieved["target"] == "hubspot"
        assert len(retrieved["claim_ids"]) == 2
        assert retrieved["decision_confidence"] == 0.72
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_decision_ledger_records_warnings():
    tmpdir = tempfile.mkdtemp()
    try:
        ledger = DecisionLedger(os.path.join(tmpdir, "test.db"))
        ledger.record_decision(
            decision_id="dec_002",
            decision_type="build_feature",
            target="x",
            priority="P1",
            suggested_action="do something",
            claim_ids=["clm_001"],
            claim_confidences=[{"claim_id": "clm_001", "confidence": 0.2, "status": "CONFLICTED"}],
            decision_confidence=0.15,
            warnings=["Claim clm_001 is CONFLICTED", "Claim clm_001 has low confidence (0.20)"],
        )

        with_warnings = ledger.get_decisions_with_warnings()
        assert len(with_warnings) >= 1
        assert with_warnings[0]["decision_id"] == "dec_002"
        assert len(with_warnings[0]["warnings"]) >= 2
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_compute_decision_confidence_no_claims():
    conf, warnings = compute_decision_confidence([])
    assert conf == 0.0
    assert "No supporting claims" in warnings


def test_compute_decision_confidence_verified_claims():
    conf, warnings = compute_decision_confidence([
        {"claim_id": "c1", "confidence": 0.85, "status": "VERIFIED"},
        {"claim_id": "c2", "confidence": 0.75, "status": "VERIFIED"},
    ])
    assert conf > 0.70
    assert len(warnings) == 0


def test_compute_decision_confidence_conflicted_claim():
    conf, warnings = compute_decision_confidence([
        {"claim_id": "c1", "confidence": 0.85, "status": "VERIFIED"},
        {"claim_id": "c2", "confidence": 0.30, "status": "CONFLICTED"},
    ])
    assert conf < 0.85  # should be dragged down by CONFLICTED
    assert any("CONFLICTED" in w for w in warnings)


def test_compute_decision_confidence_low_confidence_warning():
    conf, warnings = compute_decision_confidence([
        {"claim_id": "c1", "confidence": 0.25, "status": "HYPOTHESIS"},
    ])
    assert conf < 0.40
    assert any("low confidence" in w for w in warnings)


# ─── Validation Engine (integration) ───────────────────────────────────

def test_validation_engine_end_to_end():
    """Full Validation Engine pipeline: extract → validate → ledger."""
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        engine = ValidationEngine({
            "storage": {"path": db_path},
            "min_sources_probable": 2,
            "min_sources_verified": 3,
        })

        # Items with Algeria metadata
        items = [
            make_item("Sac 3500 DA Alger", "http://1.com", source="rss", source_name="APS Algeria"),
            make_item("Sac 3500 DA Oran", "http://2.com", source="rss", source_name="El Watan"),
            make_item("Sac 3500 DA Constantine", "http://3.com", source="rss", source_name="TSA Algerie"),
        ]
        for item in items:
            item.metadata["algeria"] = {
                "products": [{"name": "sac", "category": "bags", "price_dzd": 3500}],
                "wilayas": [],
                "wilaya_names": [],
            }

        # Run engine
        result = engine.process(items)

        # Should have validation summary on first item
        assert "_validation" in result[0].metadata
        val = result[0].metadata["_validation"]

        # Should have extracted claims
        assert val["claims_extracted"] > 0
        assert val["claims_validated"] > 0

        # The average_price claim for product:bags should be VERIFIED
        # (3 independent sources: APS, El Watan, TSA — all high-credibility)
        verified = val["newly_verified"]
        verified_entities = [c["entity"] for c in verified]
        assert any("product:bags" in e for e in verified_entities)

        # Store stats should reflect the claims
        stats = val["store_stats"]
        assert stats["total_claims"] > 0
        assert stats["total_evidence_pieces"] >= 3
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_validation_engine_records_decisions_in_ledger():
    """When Strategy Engine output is present, decisions should be recorded in ledger."""
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        engine = ValidationEngine({
            "storage": {"path": db_path},
        })

        items = [make_item("Sac 3500 DA", "http://1.com", source="rss", source_name="APS Algeria")]
        items[0].metadata["algeria"] = {
            "products": [{"name": "sac", "category": "bags", "price_dzd": 3500}],
        }
        # Add strategy output (simulating Strategy Engine)
        items[0].metadata["_strategy"] = {
            "selected": [{
                "decision": {
                    "id": "dec_test1",
                    "type": "launch_campaign",
                    "target": "bags",
                    "priority": "P1",
                    "suggested_action": "Promote bags",
                },
                "roi": 65.0,
            }],
        }
        items[0].metadata["_decisions"] = {
            "decisions": [{
                "id": "dec_test1",
                "type": "launch_campaign",
                "target": "bags",
                "priority": "P1",
                "suggested_action": "Promote bags",
            }],
        }

        result = engine.process(items)
        val = result[0].metadata["_validation"]

        # Decision should be recorded in ledger
        assert val["decisions_recorded"] >= 1
        assert val["ledger_stats"]["total_decisions"] >= 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_validation_engine_detects_missing_evidence():
    """Single-source claims should trigger missing-evidence requests."""
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmpdir, "test.db")
        engine = ValidationEngine({
            "storage": {"path": db_path},
            "min_sources_probable": 2,
        })

        items = [make_item("Sac 3500 DA", "http://1.com", source="rss", source_name="APS Algeria")]
        items[0].metadata["algeria"] = {
            "products": [{"name": "sac", "category": "bags", "price_dzd": 3500}],
        }

        result = engine.process(items)
        val = result[0].metadata["_validation"]

        # Single source → HYPOTHESIS → should trigger missing-evidence request
        assert len(val["missing_evidence_requests"]) >= 1
        assert val["missing_evidence_requests"][0]["needed_sources"] == 2
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
