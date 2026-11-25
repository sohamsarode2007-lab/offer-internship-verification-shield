"""
One place for every outbound request to a host that came from user-supplied text.

Resolve the name once, refuse unless EVERY address is public, then connect to that exact address while still
sending the real hostname for TLS (SNI + certificate check) and the Host header. Resolving separately for the
check and for the connection would let a hostile DNS server answer "public" first and "169.254.169.254" second
(DNS rebinding); here there is no second lookup to trick.

Also: no redirects are followed here (callers do that, hop by hop, through this same function), HEAD/GET only,
bodies are read in small capped pieces, and nothing is logged beyond an error class.
"""
import http.client
import ipaddress
import socket
import ssl
from typing import List, Optional, Tuple


class UnsafeTarget(Exception):
    """Host does not resolve, or resolves to anything that is not a public address."""


def public_addresses(host: str, port: int = 443) -> List[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeTarget("name does not resolve") from exc
    addresses: List[str] = []
    for info in infos:
        raw_ip = str(info[4][0]).split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError as exc:
            raise UnsafeTarget("name resolved to an invalid address") from exc
        mapped = getattr(ip, "ipv4_mapped", None)
        ip = mapped or ip
        if not ip.is_global or ip.is_multicast:
            raise UnsafeTarget("name resolves to a non-public address")
        if str(ip) not in addresses:
            addresses.append(str(ip))
    if not addresses:
        raise UnsafeTarget("name does not resolve")
    return addresses


def _connect(address: str, port: int, timeout: float) -> socket.socket:
    return socket.create_connection((address, port), timeout=timeout)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, address, timeout):
        super().__init__(host, port, timeout=timeout)
        self._address = address

    def connect(self):
        self.sock = _connect(self._address, self.port, self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, address, timeout, context):
        super().__init__(host, port, timeout=timeout, context=context)
        self._address = address

    def connect(self):
        raw = _connect(self._address, self.port, self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)   # SNI and verification use the name
        except BaseException:
            if close := getattr(raw, "close", None):
                close()
            raise


def request(method: str, scheme: str, host: str, path: str, *, timeout: float, read_bytes: int = 0,
            user_agent: str = "offer-verification-shield (link check)") -> Tuple[int, Optional[str], Optional[dict], bytes]:
    """One request. Returns (status, Location header, peer certificate or None, up to read_bytes of body).

    Raises UnsafeTarget for a non-public host and ssl.SSLCertVerificationError for a certificate that does not verify.
    """
    if scheme not in ("http", "https"):
        raise UnsafeTarget("unsupported scheme")
    port = 443 if scheme == "https" else 80
    address = public_addresses(host, port)[0]
    if scheme == "https":
        conn = _PinnedHTTPSConnection(host, port, address, timeout, ssl.create_default_context())
    else:
        conn = _PinnedHTTPConnection(host, port, address, timeout)
    try:
        conn.request(method, path or "/", headers={"User-Agent": user_agent, "Accept": "*/*", "Connection": "close"})
        cert = conn.sock.getpeercert() if scheme == "https" else None
        response = conn.getresponse()
        body = response.read(read_bytes) if read_bytes else b""
        return response.status, response.getheader("Location"), cert, body
    finally:
        conn.close()
