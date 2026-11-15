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
        "contact_email": "legal@attacker.example", "reason": "We dispute this domain."})
    assert pending.status_code == 200
    assert "scoring continues" in pending.json()["message"]
    assert not captured

    verified_request = api_client.post("/disputes", json={"indicator_type": "domain", "value": "acme.example",
        "contact_email": "legal@acme.example", "reason": "We dispute this domain."})
    assert verified_request.status_code == 200
    assert captured["domain"] == "acme.example"
    verify = api_client.get("/disputes/verify", params={"token": captured["token"]})
    assert verify.status_code == 200
    assert verify.json()["status"] == "domain_verified"
    assert api_client.get("/disputes/verify", params={"token": captured["token"]}).status_code == 400
