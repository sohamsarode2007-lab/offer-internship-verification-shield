"""Employer-published recruitment-domain advisories (TCS, Infosys, HCLTech). Offline; DNS is stubbed."""
import pytest

from app.services import brand_advisories, domain_verification, risk_scoring


def facts(company, domain):
    return {"company_name": {"value": company}, "sender_domain": {"value": domain}}


@pytest.fixture(autouse=True)
def no_dns(monkeypatch):
    """Anything past the advisory check must not touch the network."""
    unknown = {"check_name": "mx_records", "status": "unknown", "explanation": "DNS stubbed in tests."}
    monkeypatch.setattr(domain_verification, "check_mx_records", lambda host: unknown)


@pytest.mark.parametrize("company", ["Tata Consultancy Services", "TCS Ltd", "tcs"])
def test_named_employer_with_unrelated_domain_fails_with_attributed_wording(company):
    result = domain_verification.verify_domain(facts(company, "hr-desk.example"))
    assert result["status"] == "fail"
    assert "TCS recruitment fraud alert" in result["details"]
    assert "https://www.tcs.com/careers/india/recruitment-fraud-alert" in result["details"]
    assert "read 2026-11-15" in result["details"]


@pytest.mark.parametrize("domain", ["tcs.com", "careers.tcs.com"])
def test_official_domain_and_subdomain_are_not_flagged(domain):
    result = domain_verification.verify_domain(facts("Tata Consultancy Services", domain))
    assert "official recruitment domain" not in result["details"]


@pytest.mark.parametrize("company", ["Emberlake Analytics Pvt. Ltd.", "Tcsonline Tutors", "Stcs Labs", None])
def test_employers_without_an_advisory_are_not_checked(company):
    result = domain_verification.verify_domain(facts(company, "hr-desk.example"))
    assert "official recruitment domain" not in result["details"]


def test_free_mailbox_still_reports_its_own_finding_first():
    result = domain_verification.verify_domain(facts("TCS", "gmail.com"))
    assert "free mailbox" in result["details"]


def test_missing_or_broken_data_file_means_no_check(monkeypatch, tmp_path):
    bad = tmp_path / "advisories.json"
    bad.write_text("{not json")
    monkeypatch.setattr(brand_advisories, "DATA_FILE", bad)
    brand_advisories.load_advisories.cache_clear()
    try:
        assert brand_advisories.find_advisory("TCS") is None
    finally:
        brand_advisories.load_advisories.cache_clear()


def test_scoring_uses_existing_domain_weight_and_plain_reason():
    result = domain_verification.verify_domain(facts("TCS", "hr-desk.example"))
    scored = risk_scoring.calculate_risk_score([result])
    reason = next(r for r in scored["reasons"] if "recruits from" in r["text"])
    assert reason["impact"] == "+30"


@pytest.mark.parametrize("company, source_url", [
    ("Infosys Limited", "https://www.infosys.com/careers/apply/recruitment-fraud-alert.html"),
    ("HCL Technologies Ltd", "https://www.hcltech.com/careers/genuine-job-offers"),
])
def test_other_employers_with_unrelated_domain_fail_with_their_source(company, source_url):
    result = domain_verification.verify_domain(facts(company, "hr-desk.example"))
    assert result["status"] == "fail" and source_url in result["details"] and "read 2026-11-17" in result["details"]


@pytest.mark.parametrize("company, domain", [
    ("Infosys Limited", "infosys.com"), ("HCL Technologies Ltd", "hcl.com"),
    ("HCL Technologies Ltd", "hcltech.com"), ("HCLTech", "careers.hcltech.com"),
])
def test_other_employers_official_domains_pass_the_advisory_check(company, domain):
    assert "official recruitment domain" not in domain_verification.verify_domain(facts(company, domain))["details"]


@pytest.mark.parametrize("company", ["Infosys BPM Limited", "Infosys", "HCL Infosystems Ltd", "HCL Healthcare"])
def test_similar_but_different_companies_are_not_checked(company):
    result = domain_verification.verify_domain(facts(company, "hr-desk.example"))
    assert "official recruitment domain" not in result["details"]


def test_hcltech_statement_keeps_the_partner_exception_the_page_states():
    advisory = brand_advisories.find_advisory("HCL Technologies Limited")
    assert "preferred recruitment partners" in advisory["statement"]
