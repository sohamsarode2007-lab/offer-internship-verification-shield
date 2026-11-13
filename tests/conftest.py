"""
Shared test setup: keep the suite offline and hermetic.

- DATABASE_URL defaults to in-memory SQLite and the rate limiter is disabled before
  any app module is imported (one test re-enables the limiter explicitly).
- DNS is mocked per test module. WHOIS is a separate network call, so it is disabled
  here for every test: the domain-age sub-check reports "age unknown", which is
  exactly what production does when WHOIS is unreachable.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ["RATE_LIMIT_ENABLED"] = "0"

from pathlib import Path  # noqa: E402

import dns.resolver  # noqa: E402
import pytest  # noqa: E402

from app.services import domain_verification as dv  # noqa: E402

DEMO_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "demo"
DEMO_FIXTURE_DOMAINS = ("emberlakeanalytics.example,brightpathedtech.example,quillmeresoftware.example,"
                        "tarnwicklogistics.example,halvornfintech.example")
DEMO_LETTERS = ["legit_emberlake", "legit_brightpath_young_startup", "scam_fake_govt_scheme_fee",
                "registry_name_match_quillmere", "registry_struck_off_tarnwick", "registry_cin_mismatch_halvorn"]


@pytest.fixture(autouse=True)
def no_live_whois(monkeypatch):
    monkeypatch.setattr(dv, "_whois_creation_date", lambda domain: None)


@pytest.fixture(autouse=True)
def no_local_company_registry(monkeypatch, tmp_path):
    """Never read a developer's data/mca_master.sqlite3; tests that need a registry set MCA_DB_PATH."""
    monkeypatch.setenv("MCA_DB_PATH", str(tmp_path / "no-registry.sqlite3"))


def _nxdomain(name, rtype):
    raise dns.resolver.NXDOMAIN()


@pytest.fixture
def api_client(monkeypatch):
    """TestClient with an isolated in-memory DB and all DNS answering NXDOMAIN."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.database import Base, get_db
    from app.main import app

    monkeypatch.setattr(dv._resolver, "resolve", _nxdomain)
    database_url = os.environ["DATABASE_URL"]
    if database_url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool
        engine = create_engine(database_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def _test_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _test_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.fixture(scope="session")
def synthetic_registry_db(tmp_path_factory):
    """The synthetic company master loaded once per session (fictional companies only)."""
    from scripts.load_mca_master import load_csv
    db = tmp_path_factory.mktemp("registry") / "synthetic.sqlite3"
    load_csv(DEMO_DIR / "synthetic_mca_master.csv", db, synthetic=True)
    return db


@pytest.fixture
def demo_client(api_client, synthetic_registry_db, monkeypatch):
    """api_client in DEMO_MODE: fixture domains for the demo companies plus the synthetic registry."""
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_FIXTURE_DOMAINS", DEMO_FIXTURE_DOMAINS)
    monkeypatch.setenv("MCA_DB_PATH", str(synthetic_registry_db))
    return api_client
