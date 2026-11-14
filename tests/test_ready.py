from fastapi.testclient import TestClient

from app.main import app


def test_health_is_dependency_free():
    assert TestClient(app).get("/health").json()["status"] == "ok"


def test_ready_checks_database():
    response = TestClient(app).get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_returns_503_without_leaking_details(monkeypatch):
    import app.main as main

    class Broken:
        def execute(self, *_a, **_k):
            raise RuntimeError("secret connection string postgresql://u:p@h/db")

        def close(self):
            pass

    monkeypatch.setattr(main, "SessionLocal", Broken)
    response = TestClient(app).get("/ready")
    assert response.status_code == 503
    assert "postgresql" not in response.text and "secret" not in response.text
