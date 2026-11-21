"""Mark simulated demo trend rows explicitly (is_simulated).

Real checks made in DEMO_MODE are demo-flagged and unlinked too, so "is_demo and
report_id IS NULL" no longer identifies simulated rows. Before revision 006's code
change only the demo seeder wrote unlinked demo rows; that cannot be told apart from later real demo-mode
checks, so the backfill uses the seeder's report marker instead of is_demo.

Revision ID: 007_observation_is_simulated
Revises: 006_indicator_display
"""
from alembic import op
import hashlib

import sqlalchemy as sa

revision = "007_observation_is_simulated"
down_revision = "006_indicator_display"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("institution_observations") as batch:
        batch.add_column(sa.Column("is_simulated", sa.Boolean(), nullable=False, server_default=sa.false()))
    # Demo mode is NOT proof of simulation: real checks made in DEMO_MODE are demo-flagged too. Only rows
    # linked to a report carrying the demo seeder's marker (withdrawal_code_hash = sha256("demo-seed:<id>"))
    # are marked simulated; ambiguous unlinked demo rows stay unmarked (they still count only in DEMO_MODE).
    bind = op.get_bind()
    seeded = [row[0] for row in bind.execute(sa.text("SELECT id, withdrawal_code_hash FROM community_reports"))
              if row[1] == hashlib.sha256(f"demo-seed:{row[0]}".encode()).hexdigest()]
    for report_id in seeded:
        bind.execute(sa.text("UPDATE institution_observations SET is_simulated = :t WHERE report_id = :r"),
                     {"t": True, "r": report_id})


def downgrade():
    with op.batch_alter_table("institution_observations") as batch:
        batch.drop_column("is_simulated")
