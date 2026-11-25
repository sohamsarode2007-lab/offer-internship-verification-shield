"""
Request-size and concurrency limits that act before or around the heavy work.

BodyLimitMiddleware (pure ASGI) refuses an oversized body as soon as it is known: from Content-Length when
present, and by counting bytes as they arrive when it is not (chunked uploads), so the server never spools a
huge body to memory or disk before the route's own checks run. A proxy limit (nginx client_max_body_size,
Vercel/Cloud limits) should sit in front as well; this is the second line.

  MAX_REQUEST_BYTES      /analyze body cap, default 52 MB (5 files x 10 MB + form overhead)
  MAX_SMALL_BODY_BYTES   cap for every other route, default 256 KB
  ANALYZE_CONCURRENCY    simultaneous /analyze jobs per process, default 4 (extra requests wait briefly, then 503)
"""
import threading

from fastapi import HTTPException, status

from app.services.env_config import float_env

ANALYZE_PATHS = ("/analyze",)


def _limit(name: str, default: int) -> int:
    return int(float_env(name, float(default), 1024, 1024 * 1024 * 1024))


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        limit = _limit("MAX_REQUEST_BYTES", 52 * 1024 * 1024) if scope["path"] in ANALYZE_PATHS \
            else _limit("MAX_SMALL_BODY_BYTES", 256 * 1024)
        headers = dict(scope["headers"])
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > limit
            except ValueError:
                too_big = True
            if too_big:
                return await self._reject(send, limit)
        seen = 0
        rejected = False

        async def counting_receive():
            nonlocal seen, rejected
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    rejected = True
                    return {"type": "http.disconnect"}
            return message

        started = False

        async def guarded_send(message):
            nonlocal started
            if rejected:
                return
            started = started or message["type"] == "http.response.start"
            await send(message)

        await self.app(scope, counting_receive, guarded_send)
        if rejected and not started:
            await self._reject(send, limit)

    @staticmethod
    async def _reject(send, limit):
        body = b'{"detail":"The request is larger than this service accepts."}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})


_slots = threading.BoundedSemaphore(int(float_env("ANALYZE_CONCURRENCY", 4, 1, 64)))


def analyze_slot():
    """FastAPI dependency: hold one of a few analysis slots; if none frees up quickly, answer 503 instead of queueing."""
    if not _slots.acquire(timeout=float_env("ANALYZE_QUEUE_SECONDS", 3, 0, 30)):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "The service is busy checking other offers. Please try again in a minute.",
                            headers={"Retry-After": "30"})
    try:
        yield
    finally:
        _slots.release()
