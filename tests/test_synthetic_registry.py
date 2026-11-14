"""
Synthetic company-master snapshot (fixtures/demo/synthetic_mca_master.csv).

Expected bands were derived by hand from the risk_scoring.py docstring before running:
  Quillmere name match : 0 points, domain/registry offsets have nothing to offset,
                         guard met by the registry match       -> 0,  likely legitimate
  Tarnwick struck off  : +25 registry fail - 10 domain = 15 -> guard (registration failed) -> 31
  Halvorn CIN mismatch : +25 registry fail - 10 domain = 15 -> guard (registration failed) -> 31
"""
import re
import sqlite3
from pathlib import Path

import pytest

from app.services import fact_extraction, gstin_verification as gv
from conftest import DEMO_DIR
from scripts.load_mca_master import load_csv

ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC_CSV = DEMO_DIR / "synthetic_mca_master.csv"
REGISTRY_DOMAINS = ("quillmeresoftware.example,tarnwicklogistics.example,halvornfintech.example,"
                    "emberlakeanalytics.example,brightpathedtech.example")
FORBIDDEN = re.compile(r"\bofficial\b|\blive\b|\bMCA\b|data\.gov\.in", re.IGNORECASE)

QUILLMERE_CIN = "U72900MH2014PTC254318"


@pytest.fixture
def synthetic_db(tmp_path, monkeypatch):
    db = tmp_path / "synthetic.sqlite3"
    assert load_csv(SYNTHETIC_CSV, db, synthetic=True) == 13
    monkeypatch.setenv("MCA_DB_PATH", str(db))
    return db


@pytest.fixture
def registry_demo_client(api_client, synthetic_db, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_FIXTURE_DOMAINS", REGISTRY_DOMAINS)
    return api_client


def analyze(client, stem):
    text = (DEMO_DIR / f"{stem}.txt").read_text(encoding="utf-8")
    r = client.post("/analyze", data={"text": text})
    assert r.status_code == 200, r.text
    body = r.json()
    registry = next(c for c in body["checks"] if c["check_name"] == "gstin_verification")
    return body, registry


# --- The synthetic CSV itself ---------------------------------------------------

def test_synthetic_csv_is_fictional_and_well_formed():
    import csv
    rows = list(csv.DictReader(SYNTHETIC_CSV.open(encoding="utf-8")))
    assert 10 <= len(rows) <= 15
    assert all(r["Synthetic"] == "true" for r in rows)
    assert all(gv.CIN_REGEX.match(r["CIN"]) for r in rows)
    assert {"Active", "Struck Off", "Dissolved"} <= {r["CompanyStatus"] for r in rows}
    assert len({r["DateOfRegistration"][-4:] for r in rows}) >= 8


# --- Loader --------------------------------------------------------------------

def test_loader_records_synthetic_source(synthetic_db):
    with sqlite3.connect(synthetic_db) as db:
        meta = dict(db.execute("SELECT key, value FROM registry_metadata"))
    assert meta["source"] == "SYNTHETIC"
    assert meta["row_count"] == "13"


def test_loader_refuses_synthetic_rows_without_flag(tmp_path):
    with pytest.raises(ValueError, match="--synthetic"):
        load_csv(SYNTHETIC_CSV, tmp_path / "x.sqlite3")
    assert not (tmp_path / "x.sqlite3").exists()


def test_loader_never_mixes_sources(synthetic_db, tmp_path):
    plain = tmp_path / "plain.csv"
    plain.write_text("CIN,CompanyName,CompanyStatus\nU74999DL2016PTC298346,Other Example Pvt Ltd,Active\n",
                     encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to mix"):
        load_csv(plain, synthetic_db)


def test_loader_without_flag_records_mca_csv_source(tmp_path):
    plain = tmp_path / "plain.csv"
    plain.write_text("CIN,CompanyName,CompanyStatus\nU74999DL2016PTC298346,Other Example Pvt Ltd,Active\n",
                     encoding="utf-8")
    db = tmp_path / "plain.sqlite3"
    load_csv(plain, db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT value FROM registry_metadata WHERE key='source'").fetchone()[0] == "MCA_CSV"


# --- Demo-only restriction ----------------------------------------------------

@pytest.mark.parametrize("demo_mode", [None, "0"])
def test_synthetic_snapshot_ignored_outside_demo_mode(synthetic_db, monkeypatch, demo_mode):
    if demo_mode is None:
        monkeypatch.delenv("DEMO_MODE", raising=False)
    else:
        monkeypatch.setenv("DEMO_MODE", demo_mode)
    assert gv.lookup_registry(QUILLMERE_CIN, "CIN")["lookup_status"] == "db_missing"
    text = (DEMO_DIR / "registry_name_match_quillmere.txt").read_text(encoding="utf-8")
    result = gv.verify_gstin(fact_extraction.extract_facts(text))
    assert result["status"] == "insufficient_information"
    assert "registry_source" not in result
    assert "database is missing" in result["details"]


def test_synthetic_snapshot_used_in_demo_mode(synthetic_db, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    record = gv.lookup_registry(QUILLMERE_CIN, "CIN")
    assert record["lookup_status"] == "found"
    assert record["registry_source"] == "synthetic"


def test_api_outside_demo_mode_has_no_registry_source(api_client, synthetic_db, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "0")
    body, registry = analyze(api_client, "registry_name_match_quillmere")
    assert body["registry_source"] is None
    assert registry["status"] == "insufficient_information"
    assert body["risk_band"] == "insufficient evidence, verify manually"


# --- The three demo cases (bands derived by hand; see module docstring) -------

# Lead sentence of the registry details; informational state-code notes may follow it.
DEMO_CASES = [
    ("registry_name_match_quillmere", "pass", 0.0, "likely legitimate",
     "Company registry match: Quillmere Software Private Limited; Active; incorporated 2014-07-21."),
    ("registry_struck_off_tarnwick", "fail", 31.0, "insufficient evidence, verify manually",
     "Company is Struck Off in company registry records: Tarnwick Logistics Private Limited; incorporated 2011-09-04."),
    ("registry_cin_mismatch_halvorn", "fail", 31.0, "insufficient evidence, verify manually",
     "CIN belongs to a different company in company registry records: "
     "Ashcombe Data Labs Private Limited; status Active; incorporated 2019-06-18."),
]


@pytest.mark.parametrize("stem,status,score,band,details", DEMO_CASES, ids=[c[0] for c in DEMO_CASES])
def test_registry_demo_case(registry_demo_client, stem, status, score, band, details):
    body, registry = analyze(registry_demo_client, stem)
    assert registry["status"] == status
    assert registry["details"].startswith(details), registry["details"]
    assert body["overall_risk_score"] == score
    assert body["risk_band"] == band


@pytest.mark.parametrize("stem", [c[0] for c in DEMO_CASES])
def test_registry_source_is_synthetic(registry_demo_client, stem):
    body, _ = analyze(registry_demo_client, stem)
    assert body["registry_source"] == "synthetic"


@pytest.mark.parametrize("stem", [c[0] for c in DEMO_CASES])
def test_synthetic_results_have_no_forbidden_wording(registry_demo_client, stem):
    body, registry = analyze(registry_demo_client, stem)
    assert not FORBIDDEN.search(registry["details"])
    for factor in body["risk_factors"]:
        assert not FORBIDDEN.search(factor), factor
    assert not re.search(r"\bMCA\b|data\.gov\.in", body["complaint_summary"])
    assert "DEMO FIXTURE" not in registry["details"]  # no synthetic label on the website


def test_name_match_reports_company_registry_match_factor(registry_demo_client):
    body, _ = analyze(registry_demo_client, "registry_name_match_quillmere")
    assert any(f.startswith("Company registry match (-10") for f in body["risk_factors"])


def test_existing_demo_bands_unchanged_with_synthetic_registry(registry_demo_client):
    emberlake, _ = analyze(registry_demo_client, "legit_emberlake")
    brightpath, _ = analyze(registry_demo_client, "legit_brightpath_young_startup")
    scam, _ = analyze(registry_demo_client, "scam_fake_govt_scheme_fee")
    assert (emberlake["overall_risk_score"], emberlake["risk_band"]) == (0.0, "likely legitimate")
    assert (brightpath["overall_risk_score"], brightpath["risk_band"]) == (31.0, "insufficient evidence, verify manually")
    assert (scam["overall_risk_score"], scam["risk_band"]) == (100.0, "high risk")


def test_founding_claim_contradiction_note_avoids_mca_wording(synthetic_db, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    text = ("Quillmere Software Private Limited, established 2005\n"
            f"CIN: {QUILLMERE_CIN}\nContact careers@quillmeresoftware.example")
    result = gv.verify_gstin(fact_extraction.extract_facts(text))
    assert result["consistency_risk_points"] == 15
    assert result["consistency_notes"] and not FORBIDDEN.search(" ".join(result["consistency_notes"]))


# --- Website strings ------------------------------------------------------------

def test_ui_never_calls_registry_data_official_live_or_mca():
    source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert not re.search(r"\bMCA\b|data\.gov\.in|\bofficial\b", source, re.IGNORECASE)
    how = re.search(r"<h2>Company registration</h2><p>(.*?)</p>", source).group(1)
    assert "we check the CIN against company registry records" in how
    assert not FORBIDDEN.search(how)
    for sentence in re.findall(r"[^.<>]*registry[^.<>]*", source, re.IGNORECASE):
        assert not FORBIDDEN.search(sentence), sentence
