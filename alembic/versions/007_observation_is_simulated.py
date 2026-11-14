"""Mark simulated demo trend rows explicitly (is_simulated).

Real checks made in DEMO_MODE are demo-flagged and unlinked too, so "is_demo and
report_id IS NULL" no longer identifies simulated rows. Before revision 006's code
change only the demo seeder wrote unlinked demo rows, so those are backfilled.

Revision ID: 007_observation_is_simulated
Revises: 006_indicator_display
"""
from alembic import op
import sqlalchemy as sa

revision = "007_observation_is_simulated"
down_revision = "006_indicator_display"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("institution_observations") as batch:
        batch.add_column(sa.Column("is_simulated", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE institution_observations SET is_simulated = is_demo")


def downgrade():
    with op.batch_alter_table("institution_observations") as batch:
        batch.drop_column("is_simulated")
