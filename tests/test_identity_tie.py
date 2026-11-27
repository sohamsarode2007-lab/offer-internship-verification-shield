"""A company number can be copied: the registry match only counts when the domain is the company's name."""
import pytest

from app.services import risk_scoring as rs
from app.services.identity_tie import domain_tied_to_company as tied


@pytest.mark.parametrize(("domain", "name", "expected"), [
    ("emberlakeanalytics.example", "Emberlake Analytics Pvt. Ltd.", True),
    ("hr.emberlake.example", "Emberlake Analytics Pvt. Ltd.", True),        # distinctive first word
    ("infosys.example", "Infosys Limited", True),
    ("tcs.example", "Tata Consultancy Services Limited", True),             # initials of a 3+ word name
    ("ember-lake-analytics.example", "Emberlake Analytics Pvt. Ltd.", True),  # hyphens ignored
    ("nordvale.example", "Ashcombe Data Labs Private Limited", False),      # unrelated
    ("ashcombe-careers.example", "Ashcombe Data Labs Private Limited", False),  # name plus extra words
    ("ab.example", "Ab Cd Ef Limited", False),                              # label too short to mean anything
    ("jobs.example", "Jobs Limited", True),                                 # a 4+ letter first word equals the label
    (None, "Emberlake Analytics", False),
    ("emberlake.example", None, False),
])
def test_tie_rules(domain, name, expected):
    assert tied(domain, name) is expected


def _checks(domain):
    return [
        {"check_name": "domain_verification", "status": "pass", "domain": domain},
        {"check_name": "gstin_verification", "status": "pass", "identifier_present": True, "registry_checked": True,
         "verification_source": "mca_registry", "verified_identifier_type": "CIN",
         "registry_company_name": "Ashcombe Data Labs Private Limited"},
        {"check_name": "payment_detection", "status": "pass"},
    ]


def test_registry_match_with_unrelated_domain_is_manual_review_with_plain_reason():
    result = rs.calculate_risk_score(_checks("nordvale.example"))
    assert result["overall_risk_score"] == 31.0
    assert result["risk_band"] == "insufficient evidence, verify manually"
    texts = [r["text"] for r in result["reasons"]]
    assert any("company number is real, but the email domain doesn't match" in t for t in texts)


def test_registry_match_with_matching_domain_can_be_likely_legitimate():
    result = rs.calculate_risk_score(_checks("ashcombedatalabs.example"))
    assert result["overall_risk_score"] == 0.0 and result["risk_band"] == "likely legitimate"


def test_payment_demand_still_forces_high_risk_with_a_tied_domain():
    checks = _checks("ashcombedatalabs.example")
    checks[2] = {"check_name": "payment_detection", "status": "fail", "demands": ["pay Rs 500"]}
    assert rs.calculate_risk_score(checks)["risk_band"] == "high risk"
