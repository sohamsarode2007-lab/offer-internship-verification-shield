"""Replace free-text dispute reasons with a fixed code.

Free text could hold offer letters, names, phone numbers or bank details. Existing text is overwritten
(it cannot be sorted into codes automatically); the dispute rows themselves are kept.
"""
from alembic import op

revision = "008_dispute_reason_codes"
down_revision = "007_observation_is_simulated"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE community_disputes SET reason = 'legacy_redacted'")


def downgrade():
    pass  # the original free text is intentionally not recoverable
