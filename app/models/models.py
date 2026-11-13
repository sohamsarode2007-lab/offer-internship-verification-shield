import datetime
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.db.database import Base

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)

class Offer(Base):
    __tablename__ = "offers"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=True)
    company_name = Column(String(255), nullable=True)
    # DPDP: always NULL since Phase 1 (offer text is not stored). Kept for schema compatibility.
    raw_text = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    verifications = relationship("VerificationResult", back_populates="offer", cascade="all, delete-orphan")


class VerificationResult(Base):
    __tablename__ = "verification_results"

    id = Column(Integer, primary_key=True, index=True)
    offer_id = Column(Integer, ForeignKey("offers.id", ondelete="CASCADE"), nullable=False)
    overall_risk_score = Column(Float, nullable=False)
    completeness_percentage = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    offer = relationship("Offer", back_populates="verifications")
    check_results = relationship("CheckResult", back_populates="verification_result", cascade="all, delete-orphan")


class CheckResult(Base):
    __tablename__ = "check_results"

    id = Column(Integer, primary_key=True, index=True)
    verification_id = Column(Integer, ForeignKey("verification_results.id", ondelete="CASCADE"), nullable=False)
    check_name = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False)  # 'pass', 'fail', 'not_applicable', 'insufficient_information'
    score = Column(Float, nullable=True)
    details = Column(Text, nullable=True)

    verification_result = relationship("VerificationResult", back_populates="check_results")
