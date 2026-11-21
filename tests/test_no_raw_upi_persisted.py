"""A UPI handle quoted in an offer must not be returned in check text or persisted with the analysis."""
from sqlalchemy import text as sql

from app.db.database import get_db
from app.main import app

HANDLE = "candidatefees@ybl"
OFFER = f"Pay the registration fee of Rs 500 to {HANDLE} to confirm your seat."


def _rows(api_client):
    db = next(app.dependency_overrides[get_db]())
    try:
        out = []
        for table in ("check_results", "verification_results", "offers"):
            for row in db.execute(sql(f"SELECT * FROM {table}")).mappings():
                out.append(str(dict(row)))
        return "\n".join(out)
    finally:
        db.close()


def test_handle_is_not_in_the_response_or_the_database(api_client):
    body = api_client.post("/analyze", data={"text": OFFER}).json()
    assert body["risk_band"] == "high risk"
    assert HANDLE not in str(body["checks"]) + str(body["risk_factors"]) + str(body["reasons"])
    assert "candidatefees" not in _rows(api_client)


def test_payment_demand_still_found_without_echoing_the_handle():
    from app.services import fact_extraction, payment_detection
    r = payment_detection.detect_payment_demand(fact_extraction.extract_facts(OFFER))
    assert r["status"] == "fail" and "handle not shown" in r["details"] and HANDLE not in r["details"]
