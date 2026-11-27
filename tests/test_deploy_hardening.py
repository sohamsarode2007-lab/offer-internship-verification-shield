"""Security headers, production start-up guard, access-log default."""
import logging

import pytest

from app.services.env_config import production_problems

GOOD = {"ENVIRONMENT": "production", "INDICATOR_PEPPER": "x" * 40, "ALLOWED_ORIGINS": "https://shield.example",
        "DATABASE_URL": "postgresql://u:p@db/x", "FORWARDED_ALLOW_IPS": "*"}


def test_headers_on_json_and_pages(api_client):
    r = api_client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY" and r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert r.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in r.headers


def test_page_policy_allows_only_own_scripts(api_client):
    from app.api import security_headers as sh
    assert "script-src 'self'" in sh.PAGE_CSP and "unsafe-inline" not in sh.PAGE_CSP.split("style-src")[0]
    assert "frame-ancestors 'none'" in sh.PAGE_CSP and "object-src 'none'" in sh.PAGE_CSP


def test_hsts_only_when_switched_on(api_client, monkeypatch):
    monkeypatch.setenv("HSTS_ENABLED", "1")
    assert "strict-transport-security" in api_client.get("/health").headers


def test_production_guard_accepts_a_good_config_and_ignores_other_environments():
    assert production_problems(GOOD) == []
    assert production_problems({"ENVIRONMENT": "development", "ALLOWED_ORIGINS": "*"}) == []


@pytest.mark.parametrize("change,expect", [
    ({"INDICATOR_PEPPER": "short"}, "INDICATOR_PEPPER"),
    ({"ALLOWED_ORIGINS": ""}, "ALLOWED_ORIGINS"),
    ({"ALLOWED_ORIGINS": "https://a.example,http://localhost:5173"}, "localhost"),
    ({"ALLOWED_ORIGINS": "*"}, "ALLOWED_ORIGINS"),
    ({"DATABASE_URL": "sqlite:///x.db"}, "PostgreSQL"),
    ({"RATE_LIMIT_ENABLED": "0"}, "RATE_LIMIT"),
    ({"DEMO_MODE": "1"}, "DEMO_MODE"),
    ({"FORWARDED_ALLOW_IPS": ""}, "FORWARDED_ALLOW_IPS"),
])
def test_production_guard_names_each_problem(change, expect):
    problems = production_problems({**GOOD, **change})
    assert problems and any(expect in p for p in problems)


def test_app_refuses_to_start_with_a_bad_production_config(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    for k, v in {"ENVIRONMENT": "production", "INDICATOR_PEPPER": "short", "DATABASE_URL": "sqlite://"}.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(RuntimeError, match="Refusing to start in production"):
        with TestClient(app):
            pass


def test_access_log_is_off_by_default():
    import app.main  # noqa: F401
    assert logging.getLogger("uvicorn.access").disabled is True


def test_rate_limit_counters_can_be_shared_through_a_storage_uri(monkeypatch):
    from app.api.limiter import build_limiter
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", "memory://shared-test")
    assert build_limiter()._storage_uri == "memory://shared-test"
    monkeypatch.delenv("RATE_LIMIT_STORAGE_URI")
    assert build_limiter()._storage_uri == "memory://"
