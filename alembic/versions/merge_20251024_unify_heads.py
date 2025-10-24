"""Merge heads to unify Alembic history"""

from alembic import op
import sqlalchemy as sa

# Este archivo MERGE une los dos heads en uno solo.
revision = "merge_20251024_unify_heads"

# Los dos heads reales a unificar:
down_revision = ("20251013_add_trial_fields", "xxxx_unique_payment_id")

branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
