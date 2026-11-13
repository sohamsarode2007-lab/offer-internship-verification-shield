"""
End-to-end tests for the three synthetic demo documents, through POST /analyze,
via both the text path and the PDF upload path. DEMO_MODE fixtures stand in for
DNS (the .example domains never resolve); all other DNS is mocked as NXDOMAIN.
"""
import pytest

from app.services import domain_verification as dv
from conftest import DEMO_DIR, DEMO_LETTERS
from pathlib import Path

EML_DIR = Path(__file__).parent / "fixtures" / "eml"


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


@pytest.mark.parametrize("stem", DEMO_LETTERS)
def test_every_demo_pdf_matches_its_text(demo_client, stem):
    """Each offer-letter PDF has a real text layer and scores exactly like its .txt source."""
    text_body = analyze(demo_client, stem, "text")
    pdf_body = analyze(demo_client, stem, "pdf")
    assert (pdf_body["risk_band"], pdf_body["overall_risk_score"]) == \
        (text_body["risk_band"], text_body["overall_risk_score"])
    assert [c["status"] for c in pdf_body["checks"]] == [c["status"] for c in text_body["checks"]]


def test_demo_pdfs_have_text_layer_and_letter_layout():
    import pdfplumber
    for stem in DEMO_LETTERS:
        with pdfplumber.open(DEMO_DIR / f"{stem}.pdf") as pdf:
            page = pdf.pages[0]
            text = page.extract_text() or ""
            header_size = max(ch["size"] for ch in page.chars)
        source_first_line = (DEMO_DIR / f"{stem}.txt").read_text(encoding="utf-8").splitlines()[0]
        assert text.splitlines()[0] == source_first_line, stem      # company / sender header first
        assert header_size > 14, stem                                 # header set larger than body text
        assert len(text) > 400, stem                                  # real text layer, no OCR needed


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


@pytest.mark.parametrize("path", ["text", "pdf"])
def test_emberlake_matches_synthetic_registry(demo_client, path):
    body = analyze(demo_client, "legit_emberlake", path)
    registry = next(c for c in body["checks"] if c["check_name"] == "gstin_verification")
    assert registry["status"] == "pass"
    assert registry["details"].startswith("Company registry match: Emberlake Analytics Pvt. Ltd.;")
    assert body["registry_source"] == "synthetic"


def test_synthetic_registry_does_not_match_unrelated_company(demo_client):
    from app.services.fact_extraction import extract_facts
    from app.services.gstin_verification import verify_gstin

    facts = extract_facts(
        "Other Example Pvt Ltd; CIN: U74999DL2016PTC298345; "
        "GSTIN: 07AAFCE4321L1ZO; contact: hr@emberlakeanalytics.example"
    )
    result = verify_gstin(facts)
    assert result["status"] == "fail"
    assert result["details"].startswith("CIN belongs to a different company")


def _upload_eml(client, name):
    return client.post("/analyze", files={
        "file": (name, (EML_DIR / name).read_bytes(), "message/rfc822")
    })


@pytest.mark.parametrize(("name", "expected"), [
    ("authenticated_legit.eml", "likely legitimate"),
    ("dmarc_fail_spoof.eml", "insufficient evidence, verify manually"),
    ("reply_to_gmail.eml", "insufficient evidence, verify manually"),
    ("brand_display_spoof.eml", "insufficient evidence, verify manually"),
    ("forged_lower_auth_results.eml", "insufficient evidence, verify manually"),
    ("no_authentication_results.eml", "insufficient evidence, verify manually"),
    ("authenticated_with_pdf.eml", "high risk"),
])
def test_eml_analysis_signals_and_bands(demo_client, monkeypatch, name, expected):
    monkeypatch.setenv("DEMO_FIXTURE_DOMAINS", "acme.example,attacker.example,imposter.example")
    response = _upload_eml(demo_client, name)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["risk_band"] == expected
    auth = next(c for c in body["checks"] if c["check_name"] == "sender_authentication")
    if name == "authenticated_legit.eml":
        assert auth["status"] == "pass"
        assert "acme.example" in auth["details"]
        assert "likely legitimate" == body["risk_band"]
    elif name == "no_authentication_results.eml":
        assert auth["status"] == "insufficient_information"
        assert "forwarded or exported without headers" in auth["details"]
    elif name == "forged_lower_auth_results.eml":
        assert "lower Authentication-Results headers disagree" in auth["details"]
    elif name == "authenticated_with_pdf.eml":
        payment = next(c for c in body["checks"] if c["check_name"] == "payment_detection")
        assert payment["status"] == "fail"
        assert body["overall_risk_score"] >= 65


def test_non_eml_sender_auth_check_is_not_applicable(api_client):
    response = api_client.post("/analyze", data={"text": "Offer details, contact hr@acme.example."})
    assert response.status_code == 200
    auth = next(c for c in response.json()["checks"] if c["check_name"] == "sender_authentication")
    assert auth["status"] == "not_applicable"
    assert ".eml" in auth["details"]


def test_eml_response_does_not_expose_private_headers_or_addresses(demo_client, monkeypatch, caplog):
    monkeypatch.setenv("DEMO_FIXTURE_DOMAINS", "acme.example")
    response = _upload_eml(demo_client, "authenticated_legit.eml")
    assert response.status_code == 200
    assert "candidate@student.example" not in response.text
    assert "mx.receiver.example" not in response.text
    assert "smtp.mailfrom" not in response.text
    assert "candidate@student.example" not in caplog.text
    assert "mx.receiver.example" not in caplog.text


def test_eml_upload_uses_the_same_file_size_limit(api_client, monkeypatch):
    from app.api.routes import analyze

    monkeypatch.setattr(analyze, "MAX_FILE_BYTES", 16)
    response = _upload_eml(api_client, "authenticated_legit.eml")
    assert response.status_code == 413
