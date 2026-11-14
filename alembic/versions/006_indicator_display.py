"""Per-indicator masked display form, ISO week and scam category for consented reports.

Revision ID: 006_indicator_display
Revises: 005_single_college
"""
from alembic import op
import sqlalchemy as sa

revision = "006_indicator_display"
down_revision = "005_single_college"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("community_indicators") as batch:
        batch.add_column(sa.Column("masked_display", sa.String(120), nullable=True))
        batch.add_column(sa.Column("iso_week", sa.String(8), nullable=True))
        batch.add_column(sa.Column("scam_category", sa.String(50), nullable=True))
    op.create_index("ix_community_indicators_iso_week", "community_indicators", ["iso_week"])


def downgrade():
    op.drop_index("ix_community_indicators_iso_week", table_name="community_indicators")
    with op.batch_alter_table("community_indicators") as batch:
        batch.drop_column("scam_category")
        batch.drop_column("iso_week")
        batch.drop_column("masked_display")
