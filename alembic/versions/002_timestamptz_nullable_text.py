"""Timezone-aware created_at; offer text/file columns explicitly nullable

Revision ID: 002
Revises: 001
Create Date: 2026-11-12

- created_at columns become TIMESTAMP WITH TIME ZONE to match the models
  (the app writes timezone-aware UTC datetimes).
- offers.raw_text / offers.file_path are (re)declared nullable: since the DPDP fix
  the app always stores NULL in them.

SQLite has no timestamptz type and 001 already made these columns nullable,
so this migration only changes Postgres.
"""
from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None

TABLES_WITH_CREATED_AT = ("offers", "verification_results")


def upgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for table in TABLES_WITH_CREATED_AT:
        op.alter_column(table, "created_at", type_=sa.DateTime(timezone=True),
                        existing_type=sa.DateTime(), existing_nullable=True,
                        postgresql_using="created_at AT TIME ZONE 'UTC'")
    op.alter_column("offers", "raw_text", existing_type=sa.Text(), nullable=True)
    op.alter_column("offers", "file_path", existing_type=sa.String(500), nullable=True)


def downgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for table in TABLES_WITH_CREATED_AT:
        op.alter_column(table, "created_at", type_=sa.DateTime(),
                        existing_type=sa.DateTime(timezone=True), existing_nullable=True,
                        postgresql_using="created_at AT TIME ZONE 'UTC'")
