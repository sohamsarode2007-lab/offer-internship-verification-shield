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
DEMO_FIXTURE_DOMAINS = "emberlakeanalytics.example,brightpathedtech.example"


@pytest.fixture(autouse=True)
def no_live_whois(monkeypatch):
    monkeypatch.setattr(dv, "_whois_creation_date", lambda domain: None)


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


@pytest.fixture
def demo_client(api_client, monkeypatch):
    """api_client with DEMO_MODE fixtures for the two synthetic company domains."""
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_FIXTURE_DOMAINS", DEMO_FIXTURE_DOMAINS)
    return api_client
