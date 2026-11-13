"""Authenticated, aggregate-only placement cell dashboard."""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.limiter import limiter
from app.db.database import get_db
from app.services.institution_dashboard import authenticate_api_key, dashboard

router = APIRouter(prefix="/institutions", tags=["institutions"])


@router.get("/me/dashboard")
@limiter.limit("30/minute")
def institution_dashboard(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
):
    institution = authenticate_api_key(db, x_api_key)
    if institution is None:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return dashboard(db, institution.id)
