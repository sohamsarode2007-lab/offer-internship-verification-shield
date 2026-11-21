"""Disposable (throwaway) mailbox detection. Reuses the existing +30 domain-failure weight."""
import pytest

from app.services import domain_verification, fact_extraction, institution_dashboard, risk_scoring
from app.utils.email_domains import is_disposable_mailbox, is_free_mailbox


@pytest.mark.parametrize("domain", ["mailinator.com", "YOPMAIL.com", "inbox.mailinator.com", "temp-mail.org."])
def test_listed_and_subdomain_disposable_domains_match(domain):
    assert is_disposable_mailbox(domain)


@pytest.mark.parametrize("domain", ["", None, "gmail.com", "emberlake.example", "notmailinator.com",
                                    "mailinator.com.example", "mailinatorfans.example"])
def test_other_domains_do_not_match(domain):
    # gmail.com is a free mailbox, which is a different (existing) finding, not a disposable one.
    assert not is_disposable_mailbox(domain)


def test_free_mailbox_is_not_reported_as_disposable():
    assert is_free_mailbox("gmail.com") and not is_disposable_mailbox("gmail.com")
    result = domain_verification.verify_domain({"sender_domain": "gmail.com"})
    assert "free mailbox" in result["details"] and "disposable" not in result["details"]


def test_verify_domain_fails_a_disposable_mailbox_without_dns(monkeypatch):
    def no_dns(*args, **kwargs):  # the check must be decided before any network lookup
        raise AssertionError("DNS must not be queried for a disposable mailbox")
    monkeypatch.setattr(domain_verification, "check_mx_records", no_dns)
    result = domain_verification.verify_domain({"sender_domain": "mailinator.com"})
    assert result["status"] == "fail"
    assert "disposable (temporary) mailbox service 'mailinator.com'" in result["details"]


def test_sender_selection_prefers_disposable_over_a_corporate_looking_address():
    text = "Contact hr@emberlake.example or recruiter123@mailinator.com for the offer."
    assert fact_extraction.extract_facts(text)["sender_domain"]["value"] == "mailinator.com"


def test_scoring_adds_the_existing_domain_failure_points_with_plain_reason():
    check = {"check_name": "domain_verification", "status": "fail",
             "details": "Contact address uses the disposable (temporary) mailbox service 'mailinator.com'; "
                        "companies do not send offers from these."}
    scored = risk_scoring.calculate_risk_score([check])
    reason = next(r for r in scored["reasons"] if "temporary throwaway mailbox" in r["text"])
    assert reason["impact"] == "+30"


def test_dashboard_category_for_disposable_sender_is_the_mailbox_category():
    domain = {"check_name": "domain_verification", "status": "fail",
              "details": "Contact address uses the disposable (temporary) mailbox service 'mailinator.com'."}
    assert institution_dashboard.classify_scam([domain], "Please reply soon.") == "free_mailbox_impersonation"
