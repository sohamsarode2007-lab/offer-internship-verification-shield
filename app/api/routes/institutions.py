"""VIT Pune placement-cell dashboard (single-college simulation).

There is no staff login yet (future scope): the page shows only aggregate weekly
counts with cells below five suppressed.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.limiter import limiter
from app.db.database import get_db
from app.services.institution_dashboard import dashboard

router = APIRouter(prefix="/placement-cell", tags=["placement-cell"])


@router.get("/dashboard")
@limiter.limit("30/minute")
def placement_cell_dashboard(request: Request, db: Session = Depends(get_db)):
    return dashboard(db)
