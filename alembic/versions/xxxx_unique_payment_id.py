# alembic/versions/xxxx_unique_payment_id.py
from alembic import op
import sqlalchemy as sa

revision = "xxxx_unique_payment_id"
down_revision = "<poné la anterior>"

def upgrade():
    op.create_unique_constraint(
        "uq_paymenthistory_payment_id",
        "payment_history",
        ["payment_id"],
    )

def downgrade():
    op.drop_constraint("uq_paymenthistory_payment_id", "payment_history", type_="unique")
