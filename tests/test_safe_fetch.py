"""Pinned-address client: resolve once, public only, connect to the address that was checked."""
import socket
import ssl

import pytest

from app.services import safe_fetch as sf


def addr(ip, family=socket.AF_INET):
    return (family, socket.SOCK_STREAM, 6, "", (ip, 443))


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.1.1", "169.254.169.254",
                                "100.64.0.1", "0.0.0.0", "224.0.0.1", "::1", "fe80::1", "fc00::1",
                                "::ffff:127.0.0.1", "::ffff:169.254.169.254"])
def test_non_public_addresses_are_refused(monkeypatch, ip):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    monkeypatch.setattr(sf.socket, "getaddrinfo", lambda *a, **k: [addr(ip, family)])
    with pytest.raises(sf.UnsafeTarget):
        sf.public_addresses("x.example")


def test_one_private_answer_among_public_ones_refuses_the_host(monkeypatch):
    monkeypatch.setattr(sf.socket, "getaddrinfo", lambda *a, **k: [addr("93.184.216.34"), addr("10.0.0.1")])
    with pytest.raises(sf.UnsafeTarget):
        sf.public_addresses("x.example")


def test_unresolvable_and_empty_answers_are_refused(monkeypatch):
    def fail(*a, **k):
        raise socket.gaierror("no")
    monkeypatch.setattr(sf.socket, "getaddrinfo", fail)
    with pytest.raises(sf.UnsafeTarget):
        sf.public_addresses("x.example")
    monkeypatch.setattr(sf.socket, "getaddrinfo", lambda *a, **k: [])
    with pytest.raises(sf.UnsafeTarget):
        sf.public_addresses("x.example")


def test_dns_rebinding_cannot_redirect_the_connection(monkeypatch):
    """First answer public, any later answer internal: only one lookup happens and it is the one we connect to."""
    answers = iter([[addr("93.184.216.34")], [addr("169.254.169.254")], [addr("169.254.169.254")]])
    lookups = []
    monkeypatch.setattr(sf.socket, "getaddrinfo", lambda *a, **k: lookups.append(a) or next(answers))
    connected = []

    class Boom(Exception):
        pass

    def fake_connect(address, port, timeout):
        connected.append((address, port))
        raise Boom                                     # stop after recording where we would have connected

    monkeypatch.setattr(sf, "_connect", fake_connect)
    with pytest.raises(Boom):
        sf.request("HEAD", "http", "rebind.example", "/", timeout=1)
    assert connected == [("93.184.216.34", 80)] and len(lookups) == 1


def test_https_uses_the_name_for_sni_while_connecting_to_the_checked_address(monkeypatch):
    monkeypatch.setattr(sf.socket, "getaddrinfo", lambda *a, **k: [addr("93.184.216.34")])
    monkeypatch.setattr(sf, "_connect", lambda a, p, t: object())
    seen = {}

    class Ctx:
        verify_mode = ssl.CERT_REQUIRED
        check_hostname = True

        def wrap_socket(self, raw, server_hostname=None):
            seen["sni"] = server_hostname
            raise RuntimeError("stop")

    monkeypatch.setattr(sf.ssl, "create_default_context", lambda: Ctx())
    with pytest.raises(RuntimeError):
        sf.request("HEAD", "https", "good.example", "/", timeout=1)
    assert seen["sni"] == "good.example"


def test_only_http_and_https_are_allowed():
    with pytest.raises(sf.UnsafeTarget):
        sf.request("GET", "file", "x.example", "/", timeout=1)
