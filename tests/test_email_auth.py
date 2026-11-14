from pathlib import Path

import pytest

from app.services import email_auth
from app.services.fact_extraction import extract_facts

FIXTURES = Path(__file__).parent / "fixtures" / "eml"


def parsed(name):
    return email_auth.parse_eml((FIXTURES / name).read_bytes())


def test_authenticated_sender_pass_and_authserv_id_internal_only():
    message = parsed("authenticated_legit.eml")
    check = email_auth.verify_sender_authentication(message, extract_facts(message["body_text"]))
    assert check["status"] == "pass"
    assert check["authserv_id"] == "mx.receiver.example"
    assert check["dkim_aligned"] is True
    assert check["sender_domain"] == "acme.example"


def test_dmarc_fail_adds_thirty():
    message = parsed("dmarc_fail_spoof.eml")
    check = email_auth.verify_sender_authentication(message, extract_facts(message["body_text"]))
    assert check["status"] == "fail"
    assert check["risk_points"] == 45  # DMARC fail + body/From mismatch


def test_absent_dmarc_with_spf_and_dkim_failure_adds_thirty():
    message = {"sender_domain": "attacker.example", "authserv_id": "mx.example",
               "auth_headers": ["mx.example; spf=fail; dkim=fail header.d=attacker.example"]}
    check = email_auth.verify_sender_authentication(message, {})
    assert check["status"] == "fail"
    assert check["dmarc_status"] is None
    assert check["risk_points"] == 30


def test_reply_to_free_mail_adds_twenty_five():
    message = parsed("reply_to_gmail.eml")
    check = email_auth.verify_sender_authentication(message, extract_facts(message["body_text"]))
    assert check["status"] == "fail"
    assert check["risk_points"] == 25


def test_protected_brand_display_spoof_adds_twenty_five():
    message = parsed("brand_display_spoof.eml")
    check = email_auth.verify_sender_authentication(message, extract_facts(message["body_text"]))
    assert check["status"] == "fail"
    assert check["risk_points"] == 25


def test_only_topmost_authentication_results_is_trusted():
    message = parsed("forged_lower_auth_results.eml")
    check = email_auth.verify_sender_authentication(message, extract_facts(message["body_text"]))
    assert check["status"] == "fail"
    assert check["risk_points"] == 30
    assert check["lower_auth_results_disagree"] is True
    assert "ignored as untrusted" in check["details"]


def test_missing_authentication_results_is_insufficient_information():
    message = parsed("no_authentication_results.eml")
    check = email_auth.verify_sender_authentication(message, extract_facts(message["body_text"]))
    assert check["status"] == "insufficient_information"
    assert "forwarded or exported without headers" in check["details"]


def test_pdf_attachment_is_extracted_for_existing_ingestion_path():
    message = parsed("authenticated_with_pdf.eml")
    assert len(message["attachments"]) == 1
    attachment = message["attachments"][0]
    assert attachment["filename"] == "email-attachment.pdf"
    assert attachment["data"].startswith(b"%PDF")


def test_html_body_fallback_is_converted_to_text():
    raw = (b"From: HR <hr@acme.example>\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
           b"<html><body><p>Offer for Acme</p><p>No fee.</p></body></html>")
    message = email_auth.parse_eml(raw)
    assert "Offer for Acme" in message["body_text"]
    assert "No fee." in message["body_text"]


def test_body_domain_subdomain_of_sender_registrable_domain_is_not_mismatch():
    check = email_auth.verify_sender_authentication(
        {"sender_domain": "hr.acme.example", "auth_headers": []},
        {"sender_domain": {"value": "acme.example"}},
    )
    assert check["risk_points"] == 0
    assert "differs from the authenticated From domain" not in check["details"]


def test_body_domain_with_different_registrable_domain_is_mismatch():
    check = email_auth.verify_sender_authentication(
        {"sender_domain": "acme.example", "auth_headers": []},
        {"sender_domain": {"value": "acme-hr.example"}},
    )
    assert check["risk_points"] == 15
    assert "differs from the authenticated From domain (+15)" in check["details"]


def test_body_domain_uses_co_in_registrable_suffix_rules():
    check = email_auth.verify_sender_authentication(
        {"sender_domain": "mail.acme.co.in", "auth_headers": []},
        {"sender_domain": {"value": "careers.acme.co.in"}},
    )
    assert check["risk_points"] == 0
