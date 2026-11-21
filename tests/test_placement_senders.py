"""public scam-trends senders table and CSV export (consented v3 reports only)."""
import csv
import io
import uuid

import pytest

from app.services import community_reports as cr
from app.services import institution_dashboard as dash


@pytest.fixture
def db(api_client, monkeypatch):
    from app.db.database import get_db
    from app.main import app
    monkeypatch.setenv("INDICATOR_PEPPER", "senders-test-pepper")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    gen = app.dependency_overrides[get_db]()
    session = next(gen)
    yield session
    gen.close()


def _indicator(kind, value):
    return {"indicator_type": kind, "digest": cr._digest(kind, value, "senders-test-pepper"), "key_version": 1,
            "masked": cr.masked(kind, value), "normalized_value": cr.normalize(kind, value)}


def _report(db, indicators, band="high risk", category="security_deposit", consent=True):
    text = "Synthetic offer " + uuid.uuid4().hex + " asks for a deposit before joining the remote role."
    token, _ = cr.issue_report_token(db, indicators, cr.minhash_signature(text), band=band, scam_category=category)
    if consent:
        selected = [i["indicator_type"] + ":" + i["digest"] for i in indicators]
        return cr.accept_report(db, token, selected, True, cr.CONSENT_VERSION)
    db.commit()
    return None


def _sender(db, masked_value):
    return next((s for s in dash.top_senders(db) if s["indicator"] == masked_value), None)


def test_sender_appears_only_at_three_reports(db):
    upi = _indicator("upi", f"fees{uuid.uuid4().hex[:8]}@ybl")
    for _ in range(2):
        _report(db, [upi])
    assert _sender(db, upi["masked"]) is None          # 2 reports: never shown
    _report(db, [upi])
    sender = _sender(db, upi["masked"])
    assert sender["reports"] == 3 and sender["indicator_type"] == "upi"
    assert sender["most_common_category"] == "security_deposit"
    assert sender["first_week"] == sender["last_week"] == dash.current_iso_week()
    assert sender["dispute_status"] is None


def test_no_indicator_or_observation_without_consent(db):
    from app.models.models import CommunityIndicator, InstitutionObservation
    upi = _indicator("upi", f"noconsent{uuid.uuid4().hex[:8]}@ybl")
    before_obs = db.query(InstitutionObservation).count()
    for _ in range(3):
        _report(db, [upi], consent=False)
    assert db.query(CommunityIndicator).filter_by(digest=upi["digest"]).count() == 0
    assert db.query(InstitutionObservation).count() == before_obs
    assert _sender(db, upi["masked"]) is None


@pytest.mark.parametrize("kind,value", [
    ("email", "placement.desk.{u}@gmail.com"),
    ("email", "hr@{u}.example"),
    ("upi", "careerdesk.{u}@ybl"),
    ("upi", "ab@ybl"),
    ("phone", "+91 98{d}"),
    ("bank", "12345678{d}|HDFC0001234"),
])
def test_masked_forms_never_contain_the_full_value(db, kind, value):
    u = uuid.uuid4().hex[:6]
    value = value.format(u=u, d=str(uuid.uuid4().int)[:8])
    item = _indicator(kind, value)
    for _ in range(3):
        _report(db, [item])
    sender = _sender(db, item["masked"])
    assert sender is not None
    shown = sender["indicator"].casefold()
    full = cr.normalize(kind, value).casefold()
    assert full not in shown
    assert "•••" in shown
    if kind in ("email", "upi"):
        local = value.split("@")[0].casefold()
        assert local not in shown                        # never the whole local part


def test_sender_domain_is_shown_in_full(db):
    domain = f"quillmere-careers-{uuid.uuid4().hex[:6]}.example"
    item = _indicator("domain", domain)
    for _ in range(3):
        _report(db, [item], category="lookalike_domain")
    assert _sender(db, domain)["most_common_category"] == "lookalike_domain"


def test_disputed_sender_shows_status(db):
    from app.models.models import CommunityDispute
    item = _indicator("domain", f"disputed-{uuid.uuid4().hex[:6]}.example")
    for _ in range(4):
        _report(db, [item])
    db.add(CommunityDispute(indicator_type="domain", digest=item["digest"], key_version=1,
                            contact_email="legal@company.example", reason="We are a real company."))
    db.commit()
    assert _sender(db, item["masked"])["dispute_status"] == "disputed by the company, under review"


def test_withdrawn_reports_stop_counting(db):
    item = _indicator("upi", f"withdraw{uuid.uuid4().hex[:8]}@ybl")
    codes = [_report(db, [item])["withdrawal_code"] for _ in range(3)]
    assert _sender(db, item["masked"])["reports"] == 3
    cr.withdraw_report(db, codes[0])
    assert _sender(db, item["masked"]) is None


def test_older_consent_versions_are_not_shown(db):
    from app.models.models import CommunityReport
    item = _indicator("upi", f"oldconsent{uuid.uuid4().hex[:8]}@ybl")
    for _ in range(3):
        _report(db, [item])
    ids = {i.report_id for i in db.query(cr.CommunityIndicator).filter_by(digest=item["digest"])}
    db.query(CommunityReport).filter(CommunityReport.id.in_(ids)).update({"consent_version": 2},
                                                                         synchronize_session=False)
    db.commit()
    assert _sender(db, item["masked"]) is None


def test_dashboard_api_and_csv_export(api_client, db):
    local = f"=cmd{uuid.uuid4().hex[:6]}"                                     # formula-like on purpose
    item = _indicator("email", f"{local}@scam.example")
    for _ in range(3):
        _report(db, [item], category="registration_fee")
    body = api_client.get("/trends/dashboard").json()
    assert body["sender_threshold"] == 3
    counts = [s["reports"] for s in body["top_senders"]]
    assert counts == sorted(counts, reverse=True)
    assert all(s["reports"] >= 3 for s in body["top_senders"])

    response = api_client.get("/trends/senders.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == list(dash.SENDER_CSV_COLUMNS)
    row = next(r for r in rows[1:] if r[0] == "'" + item["masked"])     # formula injection neutralised
    assert row[1:3] == ["email", "3"] and row[5] == "registration_fee" and row[6] == "not disputed"
    assert local not in response.text and local not in api_client.get("/trends/dashboard").text
