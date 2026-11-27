"""data.gov.in company-master lookup by CIN. All HTTP is mocked; every company is fictional."""
import csv
import json
import logging
import sqlite3

import pytest

from app.services import fact_extraction, gstin_verification as gv, ogd_registry
from scripts.load_mca_master import load_csv

CIN = "U74999DL2016PTC298345"
GSTIN = "07AAFCE4321L1ZO"
NAME = "Emberlake Analytics Pvt. Ltd."
KEY = "test-key-not-a-real-secret"


def row(**overrides):
    base = {"CIN": CIN, "CompanyName": "EMBERLAKE ANALYTICS PRIVATE LIMITED", "CompanyStatus": "Active",
            "CompanyRegistrationdate_date": "2016-03-15"}
    base.update(overrides)
    return base


@pytest.fixture
def ogd(monkeypatch, tmp_path):
    """Key set, no local DB, DEMO_MODE off; returns a list recording requested URLs."""
    monkeypatch.setenv("DATA_GOV_IN_API_KEY", KEY)
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setenv("MCA_DB_PATH", str(tmp_path / "missing.sqlite3"))
    calls = []

    def install(payload=None, exc=None):
        def fake_open(url):
            calls.append(url)
            if exc:
                raise exc
            return json.dumps(payload).encode()
        monkeypatch.setattr(ogd_registry, "_open", fake_open)
    install.calls = calls
    return install


def verify(text=f"{NAME}\nCIN: {CIN}\nGSTIN: {GSTIN}"):
    return gv.verify_gstin(fact_extraction.extract_facts(text))


def test_found_active_name_matched_cin_passes_with_ogd_source(ogd):
    ogd({"records": [row()]})
    result = verify()
    assert result["status"] == "pass"
    assert result["registry_source"] == "ogd"
    assert result["verification_source"] == "mca_registry"
    assert "filters[CIN]=" + CIN in ogd.calls[0].replace("%5B", "[").replace("%5D", "]")


def test_zero_rows_is_not_found_and_adds_no_risk(ogd):
    ogd({"records": []})
    result = verify()
    assert result["status"] == "insufficient_information"
    assert "was not found in the company registry records" in result["details"]


def test_inactive_status_fails(ogd):
    ogd({"records": [row(CompanyStatus="Strike Off")]})
    assert verify()["status"] == "fail"


@pytest.mark.parametrize("failure", [TimeoutError("slow"), OSError("blocked"), ValueError("bad")])
def test_network_failure_is_not_reported_as_not_found(ogd, failure):
    ogd(exc=failure)
    result = verify()
    assert result["status"] == "insufficient_information"
    assert "not found" not in result["details"]
    assert result.get("registry_checked") is not True


def test_bad_payload_shapes_are_unavailable(ogd):
    for payload in ({"records": "x"}, {"nope": 1}, [], {"records": [row(CompanyName="")]}):
        ogd(payload)
        assert ogd_registry.fetch_company_by_cin(CIN)[0] == ogd_registry.UNAVAILABLE


def test_rows_for_a_different_cin_mean_filter_was_ignored_so_unavailable(ogd):
    ogd({"records": [row(CIN="L22210MH1995PLC084781")]})
    assert ogd_registry.fetch_company_by_cin(CIN)[0] == ogd_registry.UNAVAILABLE


def test_no_key_means_no_network_call(monkeypatch, ogd):
    monkeypatch.delenv("DATA_GOV_IN_API_KEY")
    ogd({"records": [row()]})
    assert verify()["status"] == "insufficient_information"
    assert ogd.calls == []


def test_removed_demo_switch_does_not_disable_live_lookup(monkeypatch, ogd):
    monkeypatch.setenv("DEMO_MODE", "1")
    ogd({"records": [row()]})
    verify()
    assert len(ogd.calls) == 1


@pytest.mark.parametrize("bad", ["", "short", "u74999dl2016ptc29834", CIN + "X", "U74999DL2016PTC298345&x=1"])
def test_invalid_cin_never_reaches_the_network(ogd, bad):
    ogd({"records": [row()]})
    assert ogd_registry.fetch_company_by_cin(bad)[0] == ogd_registry.UNAVAILABLE
    assert ogd.calls == []


def test_key_is_never_logged(ogd, caplog):
    ogd(exc=OSError(f"https://api.data.gov.in/resource/x?api-key={KEY}"))
    with caplog.at_level(logging.DEBUG):
        ogd_registry.fetch_company_by_cin(CIN)
    assert KEY not in caplog.text


def test_local_snapshot_wins_over_live_call(ogd, tmp_path, monkeypatch):
    source = tmp_path / "m.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["CIN", "CompanyName", "CompanyStatus", "DateOfRegistration"])
        writer.writeheader()
        writer.writerow({"CIN": CIN, "CompanyName": NAME, "CompanyStatus": "Active", "DateOfRegistration": "15/03/2016"})
    target = tmp_path / "m.sqlite3"
    load_csv(source, target)
    monkeypatch.setenv("MCA_DB_PATH", str(target))
    ogd({"records": [row()]})
    assert verify()["registry_source"] == "mca_csv"
    assert ogd.calls == []


def test_loader_reads_data_gov_in_column_names(tmp_path):
    source = tmp_path / "ogd.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["CIN", "CompanyName", "CompanyStatus",
                                                    "CompanyRegistrationdate_date"])
        writer.writeheader()
        writer.writerow({"CIN": CIN, "CompanyName": "EMBERLAKE ANALYTICS PRIVATE LIMITED",
                         "CompanyStatus": "Active", "CompanyRegistrationdate_date": "2016-03-15"})
    target = tmp_path / "ogd.sqlite3"
    assert load_csv(source, target) == 1
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT date_of_registration FROM mca_companies").fetchone()[0] == "2016-03-15"


@pytest.mark.parametrize("letter_name", [
    "Emberlake Analytics Pvt. Ltd.", "Emberlake Analytics Private Limited",
    "EMBERLAKE ANALYTICS PVT LTD", "Emberlake Analytics Pvt Ltd.",
])
def test_abbreviated_legal_suffix_still_matches_registry_name(ogd, letter_name):
    ogd({"records": [row()]})
    assert verify(f"{letter_name}\nCIN: {CIN}\nGSTIN: {GSTIN}")["status"] == "pass"


def test_genuinely_different_company_name_still_fails(ogd):
    ogd({"records": [row()]})
    result = verify(f"Northwind Staffing Pvt. Ltd.\nCIN: {CIN}\nGSTIN: {GSTIN}")
    assert result["status"] == "fail"
    assert result["details"].startswith("CIN belongs to a different company")


@pytest.mark.parametrize("status", ["Strike Off", "Under Process of Striking Off", "Dissolved",
                                    "Under Liquidation", "Liquidated", "Amalgamated"])
def test_registry_status_variants_that_mean_not_operating_fail(ogd, status):
    ogd({"records": [row(CompanyStatus=status)]})
    assert verify()["status"] == "fail"


@pytest.mark.parametrize("status", ["Active", "Dormant"])
def test_active_or_dormant_status_is_not_treated_as_struck_off(ogd, status):
    ogd({"records": [row(CompanyStatus=status)]})
    assert verify()["status"] == "pass"
