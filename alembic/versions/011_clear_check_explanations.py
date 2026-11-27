"""Clear stored per-check explanation sentences.

They can quote a submitted domain or registration number, so the app no longer stores them (see
docs/PRIVACY_DESIGN.md). Rows written earlier are cleared here; name, status and score are kept.
"""
from alembic import op

revision = "011_clear_check_explanations"
down_revision = "010_delete_demo_rows"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE check_results SET details = NULL WHERE details IS NOT NULL")


def downgrade():
    pass   # the cleared text is gone by design
