import csv
from datetime import date

import pytest

from app.services import fact_extraction, gstin_verification as gv, risk_scoring
from scripts.load_mca_master import load_csv


CIN = "U74999DL2016PTC298345"
GSTIN = "07AAFCE4321L1ZO"
NAME = "Emberlake Analytics Pvt. Ltd."


@pytest.fixture
def mca_db(tmp_path, monkeypatch):
    source = tmp_path / "mca.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["CIN", "CompanyName", "CompanyStatus", "DateOfRegistration"])
        writer.writeheader()
        writer.writerow({"CIN": CIN, "CompanyName": NAME, "CompanyStatus": "Active",
                         "DateOfRegistration": "15/03/2016"})
    target = tmp_path / "mca.sqlite3"
    assert load_csv(source, target) == 1
    monkeypatch.setenv("MCA_DB_PATH", str(target))
    monkeypatch.setenv("DEMO_MODE", "0")
    return source, target


def facts(text):
    return fact_extraction.extract_facts(text)


def test_loader_and_active_name_matched_cin_pass(mca_db):
    result = gv.verify_gstin(facts(f"{NAME}\nCIN: {CIN}\nGSTIN: {GSTIN}"))
    assert result["status"] == "pass"
    assert result["registry_checked"] is True
    assert result["verification_source"] == "mca_registry"
    scored = risk_scoring.calculate_risk_score([
        {"check_name": "domain_verification", "status": "pass"}, result,
        {"check_name": "payment_detection", "status": "pass"},
    ])
    assert any("MCA registry pass (-10" in factor for factor in scored["risk_factors"])


def test_mca_name_mismatch_fails(mca_db):
    result = gv.verify_gstin(facts(f"Different Example Pvt Ltd\nCIN: {CIN}\nGSTIN: {GSTIN}"))
    assert result["status"] == "fail"
    assert result["details"].startswith(
        "CIN belongs to a different company in company registry records: Emberlake Analytics Pvt. Ltd.;")


@pytest.mark.parametrize("status", ["Struck Off", "Dissolved"])
def test_inactive_mca_status_fails(mca_db, status):
    _, db_path = mca_db
    import sqlite3
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE mca_companies SET company_status=? WHERE cin=?", (status, CIN))
    result = gv.verify_gstin(facts(f"{NAME}\nCIN: {CIN}\nGSTIN: {GSTIN}"))
    assert result["status"] == "fail"
    assert status in result["details"]


def test_cin_not_found_and_database_missing(mca_db, monkeypatch, tmp_path):
    unknown = "U74999DL2016PTC298346"
    result = gv.verify_gstin(facts(f"{NAME}\nCIN: {unknown}\nGSTIN: {GSTIN}"))
    assert result["status"] == "insufficient_information"
    assert "not found" in result["details"]
    monkeypatch.setenv("MCA_DB_PATH", str(tmp_path / "missing.sqlite3"))
    result = gv.verify_gstin(facts(f"{NAME}\nCIN: {CIN}\nGSTIN: {GSTIN}"))
    assert result["status"] == "insufficient_information"
    assert "database is missing" in result["details"]


def test_pan_initial_mismatch_adds_ten(mca_db):
    # Change the PAN name-initial position, then regenerate a valid GSTIN checksum.
    prefix = list(GSTIN[:14])
    prefix[6] = "B"
    mismatched = "".join(prefix) + gv.gstin_check_char("".join(prefix))
    result = gv.verify_gstin(facts(f"{NAME}\nCIN: {CIN}\nGSTIN: {mismatched}"))
    assert result["consistency_risk_points"] >= 10
    assert "PAN name-initial" in result["details"]


def _set_incorporation_date(db_path, value):
    import sqlite3
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE mca_companies SET date_of_registration=? WHERE cin=?", (value, CIN))


def test_recent_incorporation_without_claim_adds_no_points(mca_db):
    _, db_path = mca_db
    recent = date.today().strftime("%d/%m/%Y")
    _set_incorporation_date(db_path, recent)
    result = gv.verify_gstin(facts(f"{NAME}\nCIN: {CIN}\nGSTIN: {GSTIN}"))
    assert result["consistency_risk_points"] == 0
    assert "no founding-year/age claim" in result["details"]


def test_established_year_contradicted_by_registry_adds_fifteen(mca_db):
    _, db_path = mca_db
    _set_incorporation_date(db_path, "15/03/2025")
    result = gv.verify_gstin(facts(f"{NAME} established 2012\nCIN: {CIN}\nGSTIN: {GSTIN}"))
    assert result["consistency_risk_points"] == 15
    assert "founding-year claim 2012" in result["details"]
    assert "2025-03-15" in result["details"]


def test_established_year_within_one_year_of_registry_adds_no_points(mca_db):
    _, db_path = mca_db
    _set_incorporation_date(db_path, "15/03/2025")
    result = gv.verify_gstin(facts(f"{NAME} established 2024\nCIN: {CIN}\nGSTIN: {GSTIN}"))
    assert result["consistency_risk_points"] == 0
    assert "within one year" in result["details"]


def test_pan_initial_check_skips_checksum_invalid_gstin(mca_db):
    invalid = "27AABCZ0001E1ZY"
    assert not gv.gstin_checksum_ok(invalid)
    result = gv.verify_gstin(facts(f"Aevrion Signal Works Pvt Ltd\nGSTIN: {invalid}"))
    assert result["consistency_risk_points"] == 0
    assert "PAN name-initial" not in result["details"]


def test_gstin_cin_location_note_is_informational(mca_db):
    result = gv.verify_gstin(facts(f"{NAME}\nCIN: {CIN}\nGSTIN: {GSTIN}"))
    assert "GSTIN state: Delhi (07); CIN RoC location: Delhi (DL)" in result["details"]
    assert "informational only" in result["details"]

