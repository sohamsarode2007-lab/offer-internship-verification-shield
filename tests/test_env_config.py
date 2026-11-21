"""Optional tuning variables: bounded, never raise, https only."""
import pytest

from app.services import env_config, ogd_registry, web_archive


@pytest.mark.parametrize("raw,expected", [("", 2.5), ("abc", 2.5), ("nan", 2.5), ("0.01", 0.5),
                                          ("99", 10.0), ("4", 4.0)])
def test_float_env_clamps_and_falls_back(monkeypatch, raw, expected):
    monkeypatch.setenv("X_TIMEOUT", raw)
    assert env_config.float_env("X_TIMEOUT", 2.5, 0.5, 10.0) == expected


@pytest.mark.parametrize("raw,expected", [("", "https://d.example"), ("http://evil.example", "https://d.example"),
                                          ("https://", "https://d.example"),
                                          ("https://api2.example/", "https://api2.example")])
def test_https_url_env(monkeypatch, raw, expected):
    monkeypatch.setenv("X_URL", raw)
    assert env_config.https_url_env("X_URL", "https://d.example") == expected


def test_resource_url_default_and_override(monkeypatch):
    monkeypatch.delenv("DATA_GOV_IN_BASE_URL", raising=False)
    assert ogd_registry.resource_url() == ogd_registry.OGD_RESOURCE_URL
    monkeypatch.setenv("DATA_GOV_IN_BASE_URL", "https://ogd.example")
    assert ogd_registry.resource_url() == f"https://ogd.example/resource/{ogd_registry.RESOURCE_ID}"
    monkeypatch.setenv("DATA_GOV_IN_BASE_URL", "http://ogd.example")  # plain http is ignored
    assert ogd_registry.resource_url() == ogd_registry.OGD_RESOURCE_URL


def test_timeouts_are_read_from_the_environment(monkeypatch):
    seen = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n): return b"{}"

    def fake_urlopen(req, timeout):
        seen.setdefault("t", []).append(timeout)
        return Resp()

    monkeypatch.setattr(ogd_registry, "MIN_CALL_INTERVAL", 0)
    monkeypatch.setattr(ogd_registry.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(web_archive.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("MCA_LIVE_LOOKUP_TIMEOUT", "4")
    monkeypatch.setenv("INFRA_AGE_TIMEOUT", "6")
    ogd_registry._open("https://x.example/")
    web_archive._open("https://x.example/")
    assert seen["t"] == [4.0, 6.0]


def test_outbound_throttle_spaces_calls(monkeypatch):
    sleeps = []
    clock = iter([100.0, 100.0, 100.1, 100.6])
    monkeypatch.setattr(ogd_registry.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(ogd_registry.time, "sleep", sleeps.append)
    monkeypatch.setattr(ogd_registry, "_last_call", 0.0)
    ogd_registry._throttle()   # long ago: no wait
    ogd_registry._throttle()   # 0.1 s later: waits about 0.4 s
    assert len(sleeps) == 1 and 0.39 < sleeps[0] < 0.41
