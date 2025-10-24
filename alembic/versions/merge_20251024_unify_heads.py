# alembic/versions/merge_20251024_unify_heads.py
from alembic import op
import sqlalchemy as sa

# Este archivo MERGE une los dos heads en uno solo.
revision = "merge_20251024_unify_heads"

# Reemplazá REV_ANTERIOR_REAL por el revision id real del head anterior.
# El otro head es el de este repo: "xxxx_unique_payment_id".
down_revision = ("REV_ANTERIOR_REAL", "xxxx_unique_payment_id")

branch_labels = None
depends_on = None

def upgrade():
    pass

def downgrade():
    pass
