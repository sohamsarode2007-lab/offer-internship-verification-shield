"""VIT Pune placement-cell dashboard (single-college simulation).

There is no staff login yet (future scope): the page shows only aggregate weekly
counts with cells below five suppressed.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.limiter import limiter
from app.db.database import get_db
from app.services.institution_dashboard import dashboard, senders_csv

router = APIRouter(prefix="/placement-cell", tags=["placement-cell"])


@router.get("/dashboard")
@limiter.limit("30/minute")
def placement_cell_dashboard(request: Request, db: Session = Depends(get_db)):
    return dashboard(db)


@router.get("/senders.csv")
@limiter.limit("30/minute")
def placement_cell_senders_csv(request: Request, db: Session = Depends(get_db)):
    """Warning list export: masked senders with 3+ reports only (same fields as the page)."""
    return Response(content=senders_csv(db), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="vit-pune-warning-list.csv"',
                             "Cache-Control": "no-store"})
