"""Community indicator reports, template bands, tokens, and disputes.

Revision ID: 003_community_reports
Revises: 002_timestamptz_nullable_text
"""
from alembic import op
import sqlalchemy as sa

revision = "003_community_reports"
down_revision = "002_timestamptz_nullable_text"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "community_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("consent_version", sa.Integer(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawal_code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("withdrawn", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "community_indicators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.String(36), sa.ForeignKey("community_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("indicator_type", sa.String(24), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("report_id", "indicator_type", "digest"):
        op.create_index(f"ix_community_indicators_{col}", "community_indicators", [col])
    op.create_table(
        "community_template_bands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.String(36), sa.ForeignKey("community_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("band", sa.Integer(), nullable=False),
        sa.Column("bucket", sa.String(64), nullable=False),
    )
    op.create_index("ix_community_template_bands_report_id", "community_template_bands", ["report_id"])
    op.create_index("ix_community_template_bands_bucket", "community_template_bands", ["bucket"])
    op.create_table(
        "community_tokens",
        sa.Column("jti", sa.String(36), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_community_tokens_expires_at", "community_tokens", ["expires_at"])
    op.create_table(
        "community_disputes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("indicator_type", sa.String(24), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("contact_email", sa.String(320), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("domain_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verification_token_hash", sa.String(64), nullable=True),
        sa.Column("verification_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    for col in ("indicator_type", "digest"):
        op.create_index(f"ix_community_disputes_{col}", "community_disputes", [col])


def downgrade():
    op.drop_table("community_disputes")
    op.drop_table("community_tokens")
    op.drop_table("community_template_bands")
    op.drop_table("community_indicators")
    op.drop_table("community_reports")
