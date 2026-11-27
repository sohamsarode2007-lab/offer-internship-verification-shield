"""Security response headers (pure ASGI, so it also covers responses from static files and error handlers).

Pages get a Content-Security-Policy that allows only this site's own scripts, styles and images;
JSON/CSV responses get a policy that allows nothing. HSTS is sent only when HSTS_ENABLED=1, because it
must not be switched on for a plain-http deployment.
"""
import os

PAGE_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
API_CSP = "default-src 'none'; frame-ancestors 'none'"
COMMON = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
]


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in {h for h, _ in COMMON}
                           | {b"content-security-policy", b"strict-transport-security"}]
                is_page = any(k.lower() == b"content-type" and v.lower().startswith(b"text/html") for k, v in message.get("headers", []))
                headers += COMMON
                headers.append((b"content-security-policy", (PAGE_CSP if is_page else API_CSP).encode()))
                if os.getenv("HSTS_ENABLED") == "1":
                    headers.append((b"strict-transport-security", b"max-age=31536000"))
                if not is_page and not any(k.lower() == b"cache-control" for k, _ in headers):
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
