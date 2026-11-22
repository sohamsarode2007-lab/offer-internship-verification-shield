"""Delete leftover demo data (fictional seeded reports and simulated trend rows).

Demo seeding was removed from the app. Rows written by it (is_demo / is_simulated) are made-up
data and must never reach the public trends page, so they are removed here. Children are deleted
explicitly because SQLite does not enforce ON DELETE CASCADE unless foreign keys are switched on.
"""
from alembic import op

revision = "010_delete_demo_rows"
down_revision = "009_unique_public_institution"
branch_labels = None
depends_on = None

_DEMO_REPORTS = "SELECT id FROM community_reports WHERE is_demo = true"


def upgrade():
    op.execute(f"DELETE FROM institution_observations WHERE is_demo = true OR is_simulated = true "
               f"OR report_id IN ({_DEMO_REPORTS})")
    op.execute(f"DELETE FROM community_indicators WHERE report_id IN ({_DEMO_REPORTS})")
    op.execute(f"DELETE FROM community_template_bands WHERE report_id IN ({_DEMO_REPORTS})")
    op.execute("DELETE FROM community_reports WHERE is_demo = true")


def downgrade():
    # Deleted demo rows are not restored.
    pass
