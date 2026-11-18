"""One "Public" institution only: merge duplicates, then make the name unique.

Concurrent first requests could each create an institution; the dashboard reads only the first,
so observations on the others vanished from the aggregates. Duplicates are merged (observations
re-pointed to the lowest id) before the unique constraint is added.
"""
from alembic import op

revision = "009_unique_public_institution"
down_revision = "008_dispute_reason_codes"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE institution_observations SET institution_id = ("
        "SELECT MIN(i2.id) FROM institutions i2 WHERE i2.name = "
        "(SELECT i1.name FROM institutions i1 WHERE i1.id = institution_observations.institution_id))"
    )
    op.execute("DELETE FROM institutions WHERE id NOT IN (SELECT MIN(id) FROM institutions GROUP BY name)")
    with op.batch_alter_table("institutions") as batch:
        batch.create_unique_constraint("uq_institutions_name", ["name"])


def downgrade():
    with op.batch_alter_table("institutions") as batch:
        batch.drop_constraint("uq_institutions_name", type_="unique")
