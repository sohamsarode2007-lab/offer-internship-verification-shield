"""
End-to-end tests for the three synthetic demo documents, through POST /analyze,
via both the text path and the PDF upload path. DEMO_MODE fixtures stand in for
DNS (the .example domains never resolve); all other DNS is mocked as NXDOMAIN.
"""
import pytest

from app.services import domain_verification as dv
from conftest import DEMO_DIR


def analyze(client, stem, path):
    if path == "text":
        text = (DEMO_DIR / f"{stem}.txt").read_text(encoding="utf-8")
        r = client.post("/analyze", data={"text": text})
    else:
        pdf = (DEMO_DIR / f"{stem}.pdf").read_bytes()
        r = client.post("/analyze", files={"file": (f"{stem}.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


CASES = [
    ("legit_emberlake", "likely legitimate", 0.0),
    ("legit_brightpath_young_startup", "insufficient evidence, verify manually", 31.0),
    ("scam_fake_govt_scheme_fee", "high risk", 100.0),
]


@pytest.mark.parametrize("path", ["text", "pdf"])
@pytest.mark.parametrize("stem,expected_band,expected_score", CASES, ids=[c[0] for c in CASES])
def test_demo_document(demo_client, stem, expected_band, expected_score, path):
    body = analyze(demo_client, stem, path)
    assert body["risk_band"] == expected_band
    assert body["overall_risk_score"] == expected_score
    assert body["scoring_model"] == "rule_based_v2"


@pytest.mark.parametrize("path", ["text", "pdf"])
def test_govt_scheme_urgency(demo_client, path):
    body = analyze(demo_client, "scam_fake_govt_scheme_fee", path)
    assert any("within 24 hours" in f for f in body["risk_factors"])


@pytest.mark.parametrize("path", ["text", "pdf"])
def test_govt_scheme_payment_details_include_upi(demo_client, path):
    body = analyze(demo_client, "scam_fake_govt_scheme_fee", path)
    payment = next(c for c in body["checks"] if c["check_name"] == "payment_detection")
    assert "rky.verification@ybl" in payment["details"]


def test_stipend_vpa_is_not_a_payment_demand():
    from app.services.payment_detection import detect_payment_demand

    result = detect_payment_demand({"raw_text": "Your stipend will be credited to priya@ybl. No fee is required."})
    assert result["status"] == "pass"


@pytest.mark.parametrize("path", ["text", "pdf"])
def test_demo_fixture_is_labelled(demo_client, path):
    body = analyze(demo_client, "legit_emberlake", path)
    domain = next(c for c in body["checks"] if c["check_name"] == "domain_verification")
    assert domain["details"].startswith(dv.DEMO_PREFIX)
