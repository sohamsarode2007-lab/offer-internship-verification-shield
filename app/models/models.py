import datetime
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, Boolean
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


class CommunityReport(Base):
    __tablename__ = "community_reports"
    id = Column(String(36), primary_key=True)
    consent_version = Column(Integer, nullable=False)
    signature = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_seen_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    withdrawal_code_hash = Column(String(64), nullable=False, unique=True)
    withdrawn = Column(Boolean, default=False, nullable=False)
    is_demo = Column(Boolean, default=False, nullable=False)
    indicators = relationship("CommunityIndicator", back_populates="report", cascade="all, delete-orphan")
    bands = relationship("CommunityTemplateBand", back_populates="report", cascade="all, delete-orphan")
    observations = relationship("InstitutionObservation", back_populates="report", cascade="all, delete-orphan")


class CommunityIndicator(Base):
    __tablename__ = "community_indicators"
    id = Column(Integer, primary_key=True)
    report_id = Column(String(36), ForeignKey("community_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    indicator_type = Column(String(24), nullable=False, index=True)
    digest = Column(String(64), nullable=False, index=True)
    key_version = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_seen_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    # Consented reports only (see docs/PRIVACY_DESIGN.md): the masked display form the
    # student saw, never a raw value; plus the report's ISO week and scam category.
    masked_display = Column(String(120), nullable=True)
    iso_week = Column(String(8), nullable=True, index=True)
    scam_category = Column(String(50), nullable=True)
    report = relationship("CommunityReport", back_populates="indicators")


class CommunityTemplateBand(Base):
    __tablename__ = "community_template_bands"
    id = Column(Integer, primary_key=True)
    report_id = Column(String(36), ForeignKey("community_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    band = Column(Integer, nullable=False)
    bucket = Column(String(64), nullable=False, index=True)
    report = relationship("CommunityReport", back_populates="bands")


class CommunityToken(Base):
    __tablename__ = "community_tokens"
    jti = Column(String(36), primary_key=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at = Column(DateTime(timezone=True), nullable=True)


class CommunityDispute(Base):
    __tablename__ = "community_disputes"
    id = Column(Integer, primary_key=True)
    indicator_type = Column(String(24), nullable=False, index=True)
    digest = Column(String(64), nullable=False, index=True)
    key_version = Column(Integer, nullable=False)
    contact_email = Column(String(320), nullable=False)
    reason = Column(Text, nullable=False)
    domain_verified = Column(Boolean, default=False, nullable=False)
    verification_token_hash = Column(String(64), nullable=True)
    verification_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class Institution(Base):
    """Single aggregate record ("Public"), created automatically; no per-college data."""
    __tablename__ = "institutions"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, unique=True)
    observations = relationship("InstitutionObservation", back_populates="institution", cascade="all, delete-orphan")


class InstitutionObservation(Base):
    """One row per consented community report: week, band and scam category only."""
    __tablename__ = "institution_observations"
    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True)
    # Withdrawing the report removes its observation too.
    report_id = Column(String(36), ForeignKey("community_reports.id", ondelete="CASCADE"), nullable=True, index=True)
    iso_week = Column(String(8), nullable=False, index=True)
    band = Column(String(50), nullable=False, index=True)
    scam_category = Column(String(50), nullable=False, index=True)
    is_demo = Column(Boolean, default=False, nullable=False)
    # True only for rows written by app/services/demo_seed.py (never for a real check).
    is_simulated = Column(Boolean, default=False, nullable=False)
    institution = relationship("Institution", back_populates="observations")
    report = relationship("CommunityReport", back_populates="observations")
