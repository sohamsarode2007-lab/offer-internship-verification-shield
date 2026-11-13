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
    (GOOD + "Acme does NOT request any security deposit or training fee from candidates.", "likely legitimate"),
    (GOOD + "Kindly pay a refundable security deposit of Rs 5,000 before joining.", "high risk"),
    (GOOD + "No interview needed, just pay a security deposit of Rs 2000.", "high risk"),
    (GOOD + "Working hours: 10am-7pm. Please report today. No fee is required.", "likely legitimate"),
    (GOOD + "Your stipend will be transferred to your UPI ID priya@ybl monthly.", "likely legitimate"),
    ("Nimbus Labs\nRef: OFR-2026\nhr@nimbuslabs.example\nNo fee is required.", "insufficient evidence, verify manually"),
    ("To: priya.s@gmail.com\n" + GOOD + "No fee is required.", "likely legitimate"),
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


def test_reference_code_is_not_llpin():
    assert fe.extract_facts("Ref: OFR-2026")["llpin"]["value"] is None


def test_cin_21_chars_extracted():
    assert fe.extract_facts("CIN: U74999DL2016PTC298345")["cin"]["value"] == "U74999DL2016PTC298345"


def test_ocr_normalization_does_not_corrupt_words():
    assert normalize_ocr_characters("Infosys Partners Solutions") == "Infosys Partners Solutions"
    assert normalize_ocr_characters("Rs. 2S,OOO") == "Rs. 25,000"
