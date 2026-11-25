import json
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.models import (CommunityDispute, CommunityIndicator, CommunityReport,
    CommunityToken)
from app.services import community_reports as cr


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("INDICATOR_PEPPER", "test-secret-pepper")
    monkeypatch.setenv("INDICATOR_KEY_VERSION", "7")
    monkeypatch.delenv("INDICATOR_PEPPER_PREVIOUS", raising=False)
    monkeypatch.setenv("DEMO_MODE", "0")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def candidate(kind="upi", value="rky.verma@ybl"):
    return {"indicator_type": kind, "digest": cr._digest(kind, value, "test-secret-pepper"),
            "key_version": 7, "masked": cr.masked(kind, value), "normalized_value": cr.normalize(kind, value)}


def backdate(db, result, days):
    import hashlib
    row = db.query(CommunityReport).filter_by(
        withdrawal_code_hash=hashlib.sha256(result["withdrawal_code"].encode()).hexdigest()).one()
    row.created_at = cr._utcnow() - timedelta(days=days)
    db.commit()


def store_report(db, item=None, text="Acme offers a role and asks candidates to submit fees.", same_day=False):
    """Reports alternate between today and yesterday so they meet the two-day gate, unless same_day is set."""
    token, preview = cr.issue_report_token(db, [item] if item else [], cr.minhash_signature(text))
    result = cr.accept_report(db, token, [item["indicator_type"] + ":" + item["digest"]] if item else [], True, cr.CONSENT_VERSION)
    backdate(db, result, 0 if same_day else db.query(CommunityReport).count() % 2)
    return result, preview


def test_hmac_normalization_matches_vpa_case_insensitively(monkeypatch):
    monkeypatch.setenv("INDICATOR_PEPPER", "test-secret-pepper")
    assert cr._digest("upi", "Rky.Verma@YBL", "test-secret-pepper") == cr._digest("upi", "rky.verma@ybl", "test-secret-pepper")


def test_candidate_email_and_phone_are_never_scammer_indicators(monkeypatch):
    monkeypatch.setenv("INDICATOR_PEPPER", "test-secret-pepper")
    text = ("To: student@example.net\nDear Student\nCandidate phone: +91 9876543210\n"
            "Pay processing fee Rs 500 to rky.verma@ybl. Contact HR at +91 9123456789.")
    payment = {"status": "fail"}
    found = cr.extract_indicators(text, None, payment)
    assert all("student@example.net" not in str(x) and "9876543210" not in str(x) for x in found)
    assert any(x["indicator_type"] == "phone" and x["normalized_value"] == "+919123456789" for x in found)
    assert any(x["indicator_type"] == "upi" for x in found)


def test_authenticated_sender_is_extractable_but_to_and_cc_are_not(monkeypatch):
    monkeypatch.setenv("INDICATOR_PEPPER", "test-secret-pepper")
    text = "To: victim@example.net\nCc: copy@example.net\nDear Victim\nNo payment fee."
    parsed = {"sender_email": "hr@corp.example", "sender_domain": "corp.example"}
    found = cr.extract_indicators(text, parsed, {"status": "pass"})
    values = {x["normalized_value"] for x in found}
    assert values == {"hr@corp.example", "corp.example"}


def test_masked_preview_and_deselected_indicator_is_not_stored(db):
    upi, phone = candidate(), candidate("phone", "+91 9123456789")
    token, preview = cr.issue_report_token(db, [upi, phone], cr.minhash_signature("Pay a fee for this role."))
    assert any(x["masked"] == "rky.ver•••@ybl" for x in preview)
    selected = ["upi:" + upi["digest"]]
    cr.accept_report(db, token, selected, True, cr.CONSENT_VERSION)
    rows = db.query(CommunityIndicator).all()
    assert len(rows) == 1
    assert rows[0].indicator_type == "upi"
    assert db.query(CommunityIndicator).filter_by(digest=phone["digest"]).count() == 0


def test_report_consent_is_required_and_only_version_four_is_valid(db):
    token, _ = cr.issue_report_token(db, [], cr.minhash_signature("A template text has sufficient words to compare."))
    with pytest.raises(ValueError, match="consent"):
        cr.accept_report(db, token, [], False, cr.CONSENT_VERSION)
    for obsolete in (1, 2, 3):  # v3 named a single college; it is no longer accepted
        with pytest.raises(ValueError, match="consent"):
            cr.accept_report(db, token, [], True, obsolete)
    assert cr.CONSENT_VERSION == 4
    cr.accept_report(db, token, [], True, 4)


def test_report_token_tamper_reuse_and_expiry_are_rejected(db):
    token, _ = cr.issue_report_token(db, [], cr.minhash_signature("A sufficiently long synthetic letter template."))
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    with pytest.raises(ValueError, match="invalid report token"):
        cr.accept_report(db, tampered, [], True, cr.CONSENT_VERSION)
    cr.accept_report(db, token, [], True, cr.CONSENT_VERSION)
    with pytest.raises(ValueError, match="already used"):
        cr.accept_report(db, token, [], True, cr.CONSENT_VERSION)

    expired, _ = cr.issue_report_token(db, [], cr.minhash_signature("A second synthetic letter template."))
    payload = cr._decode_token(expired, "test-secret-pepper")
    payload["exp"] = int((cr._utcnow() - timedelta(hours=1)).timestamp())
    state = db.get(CommunityToken, payload["jti"])
    state.expires_at = cr._utcnow() - timedelta(hours=1)
    import base64, hmac, hashlib
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")
    sig = hmac.new(b"test-secret-pepper", ("report-token:" + body).encode(), hashlib.sha256).hexdigest()
    with pytest.raises(ValueError, match="expired"):
        cr.accept_report(db, body + "." + sig, [], True, cr.CONSENT_VERSION)


def test_indicator_thresholds_are_three_then_ten_reports(db):
    item = candidate()
    for _ in range(2):
        store_report(db, item)
    match = cr.lookup_community(db, [item], cr.minhash_signature("A unique incoming letter without enough common words."))
    assert match["risk_points"] == 0
    store_report(db, item)
    match = cr.lookup_community(db, [item], cr.minhash_signature("An incoming letter that does not resemble template."))
    assert match["risk_points"] == 25
    assert "reported in 3+ separate reports" in match["details"] and "3 reports" not in match["details"]
    for _ in range(7):
        store_report(db, item)
    match = cr.lookup_community(db, [item], cr.minhash_signature("An incoming letter that does not resemble template."))
    assert match["risk_points"] == 40
    assert "reported in 10+ separate reports" in match["details"] and "10 reports" not in match["details"]


def test_correlated_indicator_and_template_evidence_caps_at_forty(db):
    items = [candidate(), candidate("email", "hr@fraud.example"), candidate("domain", "fraud.example")]
    text = "A reported synthetic recruitment letter with a fee request and contact instructions."
    signature = cr.minhash_signature(text)
    for day in range(3):
        token, _ = cr.issue_report_token(db, items, signature)
        selected = [x["indicator_type"] + ":" + x["digest"] for x in items]
        backdate(db, cr.accept_report(db, token, selected, True, cr.CONSENT_VERSION), day)
    incoming = [dict(x) for x in items]
    match = cr.lookup_community(db, incoming, signature)
    assert match["risk_points"] == 40


def test_community_only_high_score_is_capped_to_manual_review():
    from app.services.risk_scoring import calculate_risk_score
    result = calculate_risk_score([
        {"check_name": "domain_verification", "status": "insufficient_information"},
        {"check_name": "gstin_verification", "status": "insufficient_information", "identifier_present": False},
        {"check_name": "payment_detection", "status": "pass"},
        {"check_name": "sender_authentication", "status": "not_applicable"},
        {"check_name": "community_reports", "status": "fail", "risk_points": 100},
    ])
    assert result["overall_risk_score"] == 60
    assert result["risk_band"] == "insufficient evidence, verify manually"
    assert "Reported by other job seekers; not enough independent evidence to call this high risk." in result["risk_factors"]


def test_payment_demand_still_allows_high_risk_with_community_evidence():
    from app.services.risk_scoring import calculate_risk_score
    result = calculate_risk_score([
        {"check_name": "domain_verification", "status": "pass"},
        {"check_name": "gstin_verification", "status": "pass", "identifier_present": True},
        {"check_name": "payment_detection", "status": "fail", "demands": ["processing fee"]},
        {"check_name": "community_reports", "status": "fail", "risk_points": 40},
    ])
    assert result["risk_band"] == "high risk"
    assert not any("not enough independent evidence to call this high risk" in x for x in result["risk_factors"])


def test_community_match_does_not_satisfy_external_verification_guard():
    from app.services.risk_scoring import calculate_risk_score
    result = calculate_risk_score([
        {"check_name": "domain_verification", "status": "pass"},
        {"check_name": "gstin_verification", "status": "pass", "identifier_present": True},
        {"check_name": "payment_detection", "status": "pass"},
        {"check_name": "community_reports", "status": "fail", "risk_points": 25,
         "details": "This upi was reported in 3+ separate reports."},
    ])
    assert result["risk_band"] == "insufficient evidence, verify manually"
    assert any("no externally verified registry match" in x
               for x in result["risk_factors"])


def test_redacted_template_match_ignores_candidate_name_and_amount():
    left = "Dear Alice,\nCandidate name: Alice\nPay Rs 5000 to join. Reply with your availability by 12/03/2026."
    right = "Dear Priya,\nCandidate name: Priya\nPay Rs 9000 to join. Reply with your availability by 22/04/2026."
    assert cr.similarity(cr.minhash_signature(left), cr.minhash_signature(right)) >= 0.8


def test_redacted_min_hash_template_match_scores_a_lightly_edited_copy(db):
    original = ("Dear Alice,\nCandidate name: Alice\nWe are pleased to offer the analyst internship. "
                "Please confirm your joining date and reply to the recruitment team. The role includes "
                "training, weekly meetings, and project work with our engineering group. Pay Rs 5000 "
                "for the required onboarding kit before you start.")
    edited = ("Dear Priya,\nCandidate name: Priya\nWe are pleased to offer the analyst internship. "
              "Please confirm your joining date and reply to the recruitment team. The role includes "
              "training, weekly meetings, and project work with our engineering group. Pay Rs 9000 "
              "for the required onboarding kit before you start.")
    original_sig = cr.minhash_signature(original)
    edited_sig = cr.minhash_signature(edited)
    assert cr.similarity(original_sig, edited_sig) >= 0.8
    token, _ = cr.issue_report_token(db, [], original_sig)
    cr.accept_report(db, token, [], True, cr.CONSENT_VERSION)
    match = cr.lookup_community(db, [], edited_sig)
    assert match["risk_points"] == 25
    assert "similar to a reported scam template" in match["details"]


def test_dispute_keeps_indicator_scoring_with_review_note(db):
    item = candidate()
    for _ in range(3):
        store_report(db, item)
    db.add(CommunityDispute(indicator_type="upi", digest=item["digest"], key_version=7,
        contact_email="legal@acme.example", reason="This is our payment address.", domain_verified=False))
    db.commit()
    match = cr.lookup_community(db, [item], cr.minhash_signature("No matching letter wording in this document."))
    assert match["risk_points"] == 25
    assert "disputed by the company, under review" in match["details"]


def test_verified_same_domain_dispute_suppresses_domain_while_unverified_does_not(db):
    item = candidate("domain", "acme.example")
    for _ in range(3):
        store_report(db, item)
    dispute = CommunityDispute(indicator_type="domain", digest=item["digest"], key_version=7,
        contact_email="legal@acme.example", reason="We dispute this.", domain_verified=False)
    db.add(dispute)
    db.commit()
    signature = cr.minhash_signature("An unrelated letter text with no shared template shingles.")
    assert cr.lookup_community(db, [item], signature)["risk_points"] == 25
    dispute.domain_verified = True
    db.commit()
    assert cr.lookup_community(db, [item], signature)["risk_points"] == 0


def test_withdrawal_deletes_report_contributions_and_code_is_single_use(db):
    item = candidate()
    result, _ = store_report(db, item)
    assert db.query(CommunityIndicator).count() == 1
    assert cr.withdraw_report(db, result["withdrawal_code"])["status"] == "withdrawn"
    assert db.query(CommunityIndicator).count() == 0
    with pytest.raises(ValueError, match="invalid"):
        cr.withdraw_report(db, result["withdrawal_code"])


def test_retention_purges_inactive_report_tokens_and_resolved_dispute_contacts(db):
    item = candidate()
    store_report(db, item)
    report = db.query(CommunityReport).first()
    report.last_seen_at = cr._utcnow() - timedelta(days=731)
    token = db.query(CommunityToken).first()
    token.expires_at = cr._utcnow() - timedelta(hours=49)
    db.add(CommunityDispute(indicator_type="upi", digest=item["digest"], key_version=7,
        contact_email="legal@acme.example", reason="Resolved.", resolved_at=cr._utcnow() - timedelta(days=366)))
    db.commit()
    cr.purge_expired(db)
    assert db.query(CommunityReport).count() == 0
    assert db.query(CommunityToken).count() == 0
    assert db.query(CommunityDispute).count() == 0


def test_database_contains_no_raw_indicator_or_offer_text(db):
    value = "rky.verma@ybl"
    text = "Dear Alice. Pay Rs 5000 to join this fictional internship."
    store_report(db, candidate("upi", value), text)
    from sqlalchemy import text as sql_text
    for table in ("community_reports", "community_indicators", "community_template_bands", "community_tokens"):
        rows = db.execute(sql_text(f"SELECT * FROM {table}")).fetchall()
        serialized = repr(rows)
        assert value not in serialized
        assert "Dear Alice" not in serialized
        assert "5000" not in serialized


def test_key_rotation_keeps_prior_hash_matchable(monkeypatch, db):
    item = candidate()
    store_report(db, item)
    monkeypatch.setenv("INDICATOR_PEPPER", "new-secret-pepper")
    monkeypatch.setenv("INDICATOR_KEY_VERSION", "8")
    monkeypatch.setenv("INDICATOR_PEPPER_PREVIOUS", "7:test-secret-pepper")
    incoming = candidate()
    incoming["key_version"] = 8
    incoming["digest"] = cr._digest("upi", incoming["normalized_value"], "new-secret-pepper")
    match = cr.lookup_community(db, [incoming], cr.minhash_signature("Unrelated incoming text with other words."))
    assert match["risk_points"] == 0  # one prior report is below the scoring threshold
    for _ in range(2):
        store_report(db, item)
    match = cr.lookup_community(db, [incoming], cr.minhash_signature("Unrelated incoming text with other words."))
    assert match["risk_points"] == 25


def test_aggregate_stats_suppress_cells_below_five(db):
    item = candidate()
    for _ in range(4):
        store_report(db, item)
    assert cr.stats(db)["indicators"] == [{"indicator_type": "upi", "reports": None, "suppressed": True}]
    store_report(db, item)
    assert cr.stats(db)["indicators"] == [{"indicator_type": "upi", "reports": 5, "suppressed": False}]


def test_rows_marked_demo_never_count(monkeypatch, db):
    item = candidate()
    monkeypatch.setenv("DEMO_MODE", "1")  # the removed demo switch has no effect
    for _ in range(3):
        store_report(db, item)
    db.query(cr.CommunityReport).update({"is_demo": True})
    match_signature = cr.minhash_signature("This unrelated text does not resemble any template.")
    assert cr.lookup_community(db, [item], match_signature)["risk_points"] == 0
    assert cr.stats(db)["indicators"] == []


def test_one_days_reports_never_count_even_at_ten(db):
    """Non-trigger for the two-day gate: a burst in one sitting adds no points and no public count."""
    item = candidate()
    for _ in range(10):
        store_report(db, item, same_day=True)
    match = cr.lookup_community(db, [item], cr.minhash_signature("An unrelated incoming letter about something else."))
    assert match["risk_points"] == 0
    assert cr.stats(db)["indicators"] == [{"indicator_type": "upi", "reports": None, "suppressed": True}]


def test_reports_across_two_days_count(db):
    item = candidate()
    store_report(db, item, same_day=True)
    store_report(db, item, same_day=True)
    r, _ = store_report(db, item, same_day=True)
    backdate(db, r, 2)
    match = cr.lookup_community(db, [item], cr.minhash_signature("An unrelated incoming letter about something else."))
    assert match["risk_points"] == 25


def test_disputes_lapse_after_ninety_days_and_are_deleted_later(db):
    item = candidate("domain", "lapse.example")
    for _ in range(3):
        store_report(db, item)
    row = CommunityDispute(indicator_type="domain", digest=item["digest"], key_version=7,
        contact_email="a@lapse.example", reason="reported_in_error", domain_verified=True)
    db.add(row)
    db.commit()
    other = cr.minhash_signature("An unrelated incoming letter about something else.")
    assert cr.lookup_community(db, [item], other)["risk_points"] == 0     # verified dispute suppresses the domain
    row.created_at = cr._utcnow() - timedelta(days=cr.DISPUTE_ACTIVE_DAYS + 1)
    db.commit()
    assert cr.lookup_community(db, [item], other)["risk_points"] == 25    # lapsed: warning counts again
    row.created_at = cr._utcnow() - timedelta(days=cr.DISPUTE_KEEP_DAYS + 1)
    db.commit()
    cr.purge_expired(db)
    assert db.query(CommunityDispute).count() == 0
