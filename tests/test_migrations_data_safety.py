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
