"""Single-college simulation: drop institution codes/API keys; link observations to reports.

Revision ID: 005_single_college
Revises: 004_institution_dashboard
"""
from alembic import op
import sqlalchemy as sa

revision = "005_single_college"
down_revision = "004_institution_dashboard"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_institutions_code", table_name="institutions")
    op.drop_index("ix_institutions_api_key_hash", table_name="institutions")
    with op.batch_alter_table("institutions") as batch:
        batch.drop_column("code")
        batch.drop_column("api_key_hash")
    # Earlier observations came from optional college codes on /analyze, not from
    # consented reports; they do not fit the new model, so they leave the live table. They are
    # copied to institution_observations_legacy first so a normal upgrade never destroys history.
    op.execute("CREATE TABLE institution_observations_legacy AS SELECT * FROM institution_observations")
    op.execute("DELETE FROM institution_observations")
    with op.batch_alter_table("institution_observations") as batch:
        batch.add_column(sa.Column("report_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_foreign_key("fk_institution_observations_report_id", "community_reports",
                                 ["report_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_institution_observations_report_id", "institution_observations", ["report_id"])


def downgrade():
    op.drop_index("ix_institution_observations_report_id", table_name="institution_observations")
    with op.batch_alter_table("institution_observations") as batch:
        batch.drop_constraint("fk_institution_observations_report_id", type_="foreignkey")
        batch.drop_column("is_demo")
        batch.drop_column("report_id")
    # Codes and keys cannot be restored; existing rows get placeholders.
    with op.batch_alter_table("institutions") as batch:
        batch.add_column(sa.Column("code", sa.String(40), nullable=False, server_default="VITPUNE"))
        batch.add_column(sa.Column("api_key_hash", sa.String(64), nullable=False, server_default="disabled"))
    op.create_index("ix_institutions_code", "institutions", ["code"], unique=True)
    op.create_index("ix_institutions_api_key_hash", "institutions", ["api_key_hash"], unique=True)
