from app.services import community_reports


OFFER = ("To: student@example.net\nDear Student\nCandidate phone: +91 9876543210\n"
         "Acme Recruiting\nPay processing fee Rs 500 to rky.verma@ybl. "
         "Contact HR at hr@acme.example or WhatsApp +91 9123456789.")


def test_analyze_preview_report_selection_and_withdrawal_flow(api_client, monkeypatch):
    monkeypatch.setenv("INDICATOR_PEPPER", "test-api-secret")
    response = api_client.post("/analyze", data={"text": OFFER})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["report_token"]
    preview = result["reportable_indicators"]
    assert preview
    labels = [x["masked"] for x in preview]
    assert "rky.ver•••@ybl" in labels
    assert all("student@example.net" not in value and "9876543210" not in value for value in labels)

    selected = [x["id"] for x in preview if x["indicator_type"] == "upi"]
    report = api_client.post("/report", json={"report_token": result["report_token"],
        "consent": True, "consent_version": 4, "selected_indicators": selected})
    assert report.status_code == 200, report.text
    withdrawal_code = report.json()["withdrawal_code"]
    stats = api_client.get("/indicators/stats").json()["indicators"]
    assert stats == [{"indicator_type": "upi", "reports": None, "suppressed": True}]
    withdrawn = api_client.post("/report/withdraw", json={"code": withdrawal_code})
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "withdrawn"
    assert api_client.get("/indicators/stats").json()["indicators"] == []
    assert api_client.post("/report/withdraw", json={"code": withdrawal_code}).status_code == 400


def test_api_rejects_missing_consent_and_reused_or_tampered_token(api_client, monkeypatch):
    monkeypatch.setenv("INDICATOR_PEPPER", "test-api-secret")
    result = api_client.post("/analyze", data={"text": OFFER}).json()
    token = result["report_token"]
    denied = api_client.post("/report", json={"report_token": token, "consent": False,
        "consent_version": 4, "selected_indicators": []})
    assert denied.status_code == 400
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert api_client.post("/report", json={"report_token": tampered, "consent": True,
        "consent_version": 4, "selected_indicators": []}).status_code == 400
    accepted = api_client.post("/report", json={"report_token": token, "consent": True,
        "consent_version": 4, "selected_indicators": []})
    assert accepted.status_code == 200
    assert api_client.post("/report", json={"report_token": token, "consent": True,
        "consent_version": 4, "selected_indicators": []}).status_code == 400


def test_dispute_paths_require_same_domain_one_time_verification(api_client, monkeypatch):
    monkeypatch.setenv("INDICATOR_PEPPER", "test-api-secret")
    captured = {}
    def capture(email, token, domain):
        captured.update(email=email, token=token, domain=domain)
        return True
    monkeypatch.setattr(community_reports, "_pepper_config", lambda: ((7, "test-api-secret"), {}))
    monkeypatch.setattr("app.api.routes.community._send_verification", capture)

    pending = api_client.post("/disputes", json={"indicator_type": "domain", "value": "acme.example",
        "contact_email": "legal@attacker.example", "reason_code": "our_business_detail"})
    assert pending.status_code == 200
    assert "scoring continues" in pending.json()["message"]
    assert not captured

    verified_request = api_client.post("/disputes", json={"indicator_type": "domain", "value": "acme.example",
        "contact_email": "legal@acme.example", "reason_code": "our_business_detail"})
    assert verified_request.status_code == 200
    assert captured["domain"] == "acme.example"
    old_style = api_client.get("/disputes/verify", params={"token": captured["token"]})
    assert "domain_verified" not in old_style.text      # a code in a URL no longer verifies anything
    verify = api_client.post("/disputes/verify", json={"token": captured["token"]})
    assert verify.status_code == 200
    assert verify.json()["status"] == "domain_verified"
    assert api_client.post("/disputes/verify", json={"token": captured["token"]}).status_code == 400


def test_dispute_reason_must_be_a_code_not_free_text(api_client, monkeypatch):
    monkeypatch.setattr(community_reports, "_pepper_config", lambda: ((7, "test-api-secret"), {}))
    body = {"indicator_type": "domain", "value": "acme.example", "contact_email": "legal@attacker.example"}
    free_text = api_client.post("/disputes", json={**body, "reason_code": "Dear Priya Sharma, account 123456789012 IFSC HDFC0001234"})
    assert free_text.status_code == 422
    old_field = api_client.post("/disputes", json={**body, "reason": "Our whole offer letter text"})
    assert old_field.status_code == 422
    ok = api_client.post("/disputes", json={**body, "reason_code": "reported_in_error"})
    assert ok.status_code == 200


def test_malformed_bank_dispute_is_a_400_not_a_500(api_client, monkeypatch):
    monkeypatch.setattr(community_reports, "_pepper_config", lambda: ((7, "test-api-secret"), {}))
    r = api_client.post("/disputes", json={"indicator_type": "bank", "value": "123",
                                           "contact_email": "legal@acme.example", "reason_code": "other"})
    assert r.status_code == 400


def test_verification_link_keeps_the_code_out_of_the_url_the_server_sees(monkeypatch):
    """The code is in the #fragment, which browsers never send to the server (and so never reaches access logs)."""
    from app.api.routes import community
    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, context=None): sent["tls_context"] = context
        def login(self, *a): pass
        def send_message(self, message): sent["body"] = message.get_content()

    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://shield.example")
    monkeypatch.setattr(community.smtplib, "SMTP", FakeSMTP)
    assert community._send_verification("legal@acme.example", "SECRETTOKEN123", "acme.example")
    assert "https://shield.example/verify-dispute#token=SECRETTOKEN123" in sent["body"]
    assert "?token=" not in sent["body"]


def test_smtp_starttls_verifies_the_server_certificate(monkeypatch):
    import ssl
    from app.api.routes import community
    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, context=None): sent["ctx"] = context
        def login(self, *a): pass
        def send_message(self, message): pass

    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://shield.example")
    monkeypatch.setattr(community.smtplib, "SMTP", FakeSMTP)
    community._send_verification("legal@acme.example", "T", "acme.example")
    assert sent["ctx"] is not None
    assert sent["ctx"].verify_mode == ssl.CERT_REQUIRED and sent["ctx"].check_hostname is True


def test_open_disputes_are_capped_per_address_and_per_indicator(api_client, monkeypatch):
    monkeypatch.setattr(community_reports, "_pepper_config", lambda: ((7, "test-api-secret"), {}))
    def file(value, email):
        return api_client.post("/disputes", json={"indicator_type": "domain", "value": value,
            "contact_email": email, "reason_code": "reported_in_error"})
    for i in range(community_reports.MAX_ACTIVE_DISPUTES_PER_EMAIL):
        assert file(f"cap{i}.example", "Same@Person.example").status_code == 200
    assert file("capx.example", "same@person.example").status_code == 429      # case-insensitive address
    assert file("capx.example", "other@person.example").status_code == 200      # other address unaffected
    for i in range(community_reports.MAX_ACTIVE_DISPUTES_PER_INDICATOR - 1):
        assert file("capx.example", f"u{i}@x.example").status_code == 200
    assert file("capx.example", "last@x.example").status_code == 429


def test_stats_and_verify_routes_are_rate_limited(api_client):
    from app.api.limiter import limiter
    limiter.enabled = True
    try:
        limiter.reset()
        codes = [api_client.post("/disputes/verify", json={"token": "x" * 30}).status_code for _ in range(12)]
        assert codes[:10] == [400] * 10 and 429 in codes[10:]
        limiter.reset()
        codes = [api_client.get("/indicators/stats").status_code for _ in range(32)]
        assert 429 in codes[30:] and set(codes[:30]) == {200}
    finally:
        limiter.reset()
        limiter.enabled = False
