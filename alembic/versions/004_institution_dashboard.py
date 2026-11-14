"""Add institution credentials and anonymized weekly dashboard aggregates.

Revision ID: 004_institution_dashboard
Revises: 003_community_reports
"""
from alembic import op
import sqlalchemy as sa

revision = "004_institution_dashboard"
down_revision = "003_community_reports"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "institutions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("api_key_hash", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_institutions_code", "institutions", ["code"], unique=True)
    op.create_index("ix_institutions_api_key_hash", "institutions", ["api_key_hash"], unique=True)
    op.create_table(
        "institution_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("iso_week", sa.String(length=8), nullable=False),
        sa.Column("band", sa.String(length=50), nullable=False),
        sa.Column("scam_category", sa.String(length=50), nullable=False),
    )
    for column in ("institution_id", "iso_week", "band", "scam_category"):
        op.create_index(f"ix_institution_observations_{column}", "institution_observations", [column])


def downgrade():
    op.drop_table("institution_observations")
    op.drop_table("institutions")
