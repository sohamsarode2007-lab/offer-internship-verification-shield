"""Migration data-safety: free text is wiped, history is kept, simulation is not guessed from demo mode."""
import sqlite3

from alembic import command
from alembic.config import Config


def _upgrade(tmp_path, monkeypatch, revision):
    url = f"sqlite:///{tmp_path / 'm.sqlite3'}"
    monkeypatch.setattr("app.db.database.DATABASE_URL", url)  # alembic/env.py imports it at run time
    cfg = Config("alembic.ini")
    command.upgrade(cfg, revision)
    return sqlite3.connect(tmp_path / "m.sqlite3")


def test_008_wipes_free_text_dispute_reasons_but_keeps_the_rows(tmp_path, monkeypatch):
    db = _upgrade(tmp_path, monkeypatch, "007_observation_is_simulated")
    db.execute("INSERT INTO community_disputes (indicator_type, digest, key_version, contact_email, reason, domain_verified, created_at)"
               " VALUES ('domain','d',1,'legal@acme.example','Priya Sharma 9123456789 bank 1234','0','2026-01-01')")
    db.commit(); db.close()
    command.upgrade(Config("alembic.ini"), "008_dispute_reason_codes")
    db = sqlite3.connect(tmp_path / "m.sqlite3")
    assert db.execute("SELECT reason FROM community_disputes").fetchall() == [("legacy_redacted",)]


def test_005_keeps_legacy_observations_in_an_archive_table(tmp_path, monkeypatch):
    db = _upgrade(tmp_path, monkeypatch, "004_institution_dashboard")
    db.execute("INSERT INTO institutions (id, name, code, api_key_hash) VALUES (1, 'Public', 'X', 'h')")
    db.execute("INSERT INTO institution_observations (institution_id, iso_week, band, scam_category)"
               " VALUES (1, '2026-W01', 'high risk', 'other')")
    db.commit(); db.close()
    command.upgrade(Config("alembic.ini"), "005_single_college")
    db = sqlite3.connect(tmp_path / "m.sqlite3")
    assert db.execute("SELECT count(*) FROM institution_observations").fetchone() == (0,)
    assert db.execute("SELECT iso_week, band FROM institution_observations_legacy").fetchall() == [("2026-W01", "high risk")]


def test_007_marks_only_seeder_rows_as_simulated(tmp_path, monkeypatch):
    import hashlib
    db = _upgrade(tmp_path, monkeypatch, "006_indicator_display")
    db.execute("INSERT INTO institutions (id, name) VALUES (1, 'Public')")
    seed_hash = hashlib.sha256(b"demo-seed:seeded-1").hexdigest()
    for rid, wh in (("seeded-1", seed_hash), ("real-demo-1", "f" * 64)):
        db.execute("INSERT INTO community_reports (id, consent_version, signature, created_at, last_seen_at,"
                   " withdrawal_code_hash, withdrawn, is_demo) VALUES (?, 4, '', '2026-01-01', '2026-01-01', ?, 0, 1)", (rid, wh))
    for rid in ("seeded-1", "real-demo-1", None):
        db.execute("INSERT INTO institution_observations (institution_id, iso_week, band, scam_category, report_id, is_demo)"
                   " VALUES (1, '2026-W01', 'high risk', 'other', ?, 1)", (rid,))
    db.commit(); db.close()
    command.upgrade(Config("alembic.ini"), "007_observation_is_simulated")
    db = sqlite3.connect(tmp_path / "m.sqlite3")
    rows = dict(db.execute("SELECT coalesce(report_id, 'unlinked'), is_simulated FROM institution_observations").fetchall())
    assert rows == {"seeded-1": 1, "real-demo-1": 0, "unlinked": 0}
