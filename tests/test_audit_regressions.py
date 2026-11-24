"""Regression tests for the audit fixes. DNS is mocked, so these run offline and in CI."""
import dns.resolver
import pytest

from app.services import (fact_extraction as fe, domain_verification as dv,
                          gstin_verification as gv, payment_detection as pd, risk_scoring as rs)
from app.services.ingestion import normalize_ocr_characters

LIVE = {"acmedata.example", "nimbuslabs.example"}


class _Txt:
    def __init__(self, t):
        self.strings = [t.encode()]


def _fake_resolve(name, rtype):
    base = name.removeprefix("_dmarc.")
    if base not in LIVE:
        raise dns.resolver.NXDOMAIN()
    if rtype == "MX":
        return [1]
    return [_Txt("v=DMARC1; p=reject")] if name.startswith("_dmarc.") else [_Txt("v=spf1 -all")]


@pytest.fixture(autouse=True)
def offline_dns(monkeypatch):
    monkeypatch.setattr(dv._resolver, "resolve", _fake_resolve)
    monkeypatch.delenv("DEMO_MODE", raising=False)


def band(text):
    f = fe.extract_facts(normalize_ocr_characters(text))
    checks = [dv.verify_domain(f), gv.verify_gstin(f), pd.detect_payment_demand(f)]
    return rs.calculate_risk_score(checks, facts=f)["risk_band"]


GOOD = "Acme Data Solutions Pvt Ltd\nGSTIN: 27AAFCA1234B1ZD\nhr@acmedata.example\n"


@pytest.mark.parametrize("text,expected", [
    (GOOD + "Acme does NOT request any security deposit or training fee from candidates.", "insufficient evidence, verify manually"),
    (GOOD + "Kindly pay a refundable security deposit of Rs 5,000 before joining.", "high risk"),
    (GOOD + "No interview needed, just pay a security deposit of Rs 2000.", "high risk"),
    (GOOD + "Working hours: 10am-7pm. Please report today. No fee is required.", "insufficient evidence, verify manually"),
    (GOOD + "Your stipend will be transferred to your UPI ID priya@ybl monthly.", "insufficient evidence, verify manually"),
    ("Nimbus Labs\nRef: OFR-2026\nhr@nimbuslabs.example\nNo fee is required.", "insufficient evidence, verify manually"),
    ("To: priya.s@gmail.com\n" + GOOD + "No fee is required.", "insufficient evidence, verify manually"),
    ("Acme Data Solutions Pvt Ltd\nGSTIN: 27AAFCA1234B1ZD\nReply to acme.hr@gmail.com", "insufficient evidence, verify manually"),
    ("Acme Data Solutions Pvt Ltd\nGSTIN: 27AAFCA1234B1Z5\nhr@acmedata.example", "insufficient evidence, verify manually"),
    ("Selected for WFH data entry. Pay registration fee Rs 499 on WhatsApp.", "high risk"),
    ("Selected for WFH data entry. Our team will WhatsApp you the tasks.", "insufficient evidence, verify manually"),
    ("Tata Consultancy Services\nContact: hr@tcs-careers.in", "insufficient evidence, verify manually"),
])
def test_bands(text, expected):
    assert band(text) == expected


def test_gstin_checksum():
    assert gv.gstin_checksum_ok("27AAPFU0939F1ZV")
    assert not gv.gstin_checksum_ok("27AAPFU0939F1Z5")


def test_format_valid_gstin_is_never_pass():
    f = fe.extract_facts(GOOD)
    assert gv.verify_gstin(f)["status"] == "insufficient_information"


def test_structural_domain_and_gstin_are_capped_at_manual_review():
    facts = fe.extract_facts(GOOD + "No fee is required.")
    checks = [dv.verify_domain(facts), gv.verify_gstin(facts), pd.detect_payment_demand(facts)]
    result = rs.calculate_risk_score(checks, facts=facts)
    assert result["overall_risk_score"] == 31.0
    assert result["risk_band"] == "insufficient evidence, verify manually"
    assert any("externally verified signal" in f for f in result["risk_factors"])


def test_external_registry_pass_satisfies_low_risk_verification_gate():
    checks = [
        {"check_name": "domain_verification", "status": "pass", "domain": "quillmere.example"},
        {"check_name": "gstin_verification", "status": "pass", "identifier_present": True,
         "registry_company_name": "Quillmere Software Private Limited",
         "registry_checked": True, "verification_source": "mca_registry",
         "verified_identifier_type": "CIN", "identifiers": [{"type": "CIN"}]},
        {"check_name": "payment_detection", "status": "pass"},
    ]
    result = rs.calculate_risk_score(checks)
    assert result["overall_risk_score"] == 0.0
    assert result["risk_band"] == "likely legitimate"


def test_uploaded_email_authentication_pass_cannot_satisfy_the_low_risk_gate():
    """Headers in an uploaded file are written by whoever made the file, so a pass is never an external signal."""
    checks = [
        {"check_name": "domain_verification", "status": "pass"},
        {"check_name": "gstin_verification", "status": "insufficient_information",
         "identifier_present": True},
        {"check_name": "sender_authentication", "status": "pass",
         "dmarc_status": "pass", "dkim_aligned": True},
        {"check_name": "payment_detection", "status": "pass"},
    ]
    result = rs.calculate_risk_score(checks)
    assert result["overall_risk_score"] == 31.0
    assert result["risk_band"] == "insufficient evidence, verify manually"
    assert not any("really came" in r["text"] for r in result["reasons"])


def test_registry_labelled_synthetic_is_always_ignored(tmp_path, monkeypatch):
    import sqlite3
    from scripts.load_mca_master import load_csv
    from conftest import DEMO_DIR
    db = tmp_path / "made-up.sqlite3"
    load_csv(DEMO_DIR / "company_registry.csv", db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE registry_metadata SET value='SYNTHETIC' WHERE key='source'")
    text = ("Emberlake Analytics Pvt. Ltd.\nCIN: U74999DL2016PTC298345\n"
            "GSTIN: 07AAFCE4321L1ZO\nhr@emberlakeanalytics.example")
    facts = fe.extract_facts(text)
    monkeypatch.setenv("MCA_DB_PATH", str(db))
    monkeypatch.setenv("DEMO_MODE", "1")
    result = gv.verify_gstin(facts)
    assert result["status"] == "insufficient_information"
    assert "registry_source" not in result


def test_reference_code_is_not_llpin():
    assert fe.extract_facts("Ref: OFR-2026")["llpin"]["value"] is None


def test_cin_21_chars_extracted():
    assert fe.extract_facts("CIN: U74999DL2016PTC298345")["cin"]["value"] == "U74999DL2016PTC298345"


def test_ocr_normalization_does_not_corrupt_words():
    assert normalize_ocr_characters("Infosys Partners Solutions") == "Infosys Partners Solutions"
    assert normalize_ocr_characters("Rs. 2S,OOO") == "Rs. 25,000"
