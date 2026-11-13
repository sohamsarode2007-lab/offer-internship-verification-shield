"""
Database setup.

- DATABASE_URL unset  -> local SQLite file (development only).
- DATABASE_URL set    -> used as-is (e.g. Postgres in docker-compose). If the driver is
  missing, startup fails loudly instead of silently switching databases.

Schema source of truth is Alembic (`alembic upgrade head`). `init_dev_db()` creates
tables directly ONLY for SQLite development databases.
"""
import os
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger(__name__)

DEFAULT_DEV_URL = "sqlite:///./verification_shield.db"
DATABASE_URL = os.getenv("DATABASE_URL") or DEFAULT_DEV_URL
IS_SQLITE = DATABASE_URL.startswith("sqlite")

connect_args = {"check_same_thread": False} if IS_SQLITE else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=not IS_SQLITE)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_dev_db() -> None:
    """Create tables for SQLite dev databases only. Postgres must be migrated with Alembic."""
    if IS_SQLITE:
        from app.models import models  # noqa: F401  (register tables)
        Base.metadata.create_all(bind=engine)
        logger.info("SQLite development database ready (tables created if missing).")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
