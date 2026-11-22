import os
import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.limiter import limiter
from app.api.routes.analyze import router as analyze_router
from app.api.routes.community import router as community_router
from app.api.routes.institutions import router as institutions_router
from app.db.database import init_dev_db, SessionLocal
from app.services.community_reports import purge_expired

# Log level comes from the LOG_LEVEL env var (default INFO). Nothing is forced to DEBUG.
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

DEFAULT_DEV_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", DEFAULT_DEV_ORIGINS).split(",") if o.strip()]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # SQLite dev only; Postgres schema is managed by `alembic upgrade head`.
    init_dev_db()
    def run_retention_purge():
        db = SessionLocal()
        try:
            purge_expired(db)
        finally:
            db.close()

    async def retention_worker():
        while True:
            try:
                await asyncio.to_thread(run_retention_purge)
            except Exception as exc:
                logging.getLogger(__name__).warning("Community retention purge failed: %s", type(exc).__name__)
            await asyncio.sleep(3600)

    task = asyncio.create_task(retention_worker())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Offer & Internship Verification Shield API",
    description="Rule-based offer checks using local MCA master data when configured (no remote registry queries).",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# No cookies or auth are used, so credentials are never allowed; this also means a
# "*" origin can never be combined with credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(analyze_router)
app.include_router(community_router)
app.include_router(institutions_router)


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "Verification Shield Backend"}


@app.get("/config")
def public_config():
    """What the page may offer. Flags only; no secrets."""
    from app.services import link_lookup
    return {"link_lookups": link_lookup.is_enabled()}


@app.get("/sources")
def data_sources():
    """How old each data source is and which optional lookups are on. No secrets, no offer data."""
    from app.services import source_freshness
    return source_freshness.build_sources()


@app.get("/ready")
def readiness_check():
    """Deep check: the database answers. Use /health for liveness (no dependencies)."""
    from fastapi import HTTPException
    from sqlalchemy import text

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        logging.getLogger(__name__).warning("Readiness check failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="database unavailable")
    finally:
        db.close()
    return {"status": "ready"}


# Serve only the production build. The Vite source index is never served directly.
frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
frontend_index = os.path.join(frontend_dist, "index.html")
if os.path.isfile(frontend_index):
    assets_dir = os.path.join(frontend_dist, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend_assets")

    @app.get("/", include_in_schema=False)
    def serve_frontend_root():
        return FileResponse(frontend_index)

    @app.get("/{frontend_path:path}", include_in_schema=False)
    def serve_frontend_route(frontend_path: str):
        return FileResponse(frontend_index)
