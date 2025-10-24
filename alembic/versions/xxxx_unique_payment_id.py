from alembic import op
import sqlalchemy as sa

revision = "xxxx_unique_payment_id"
down_revision = None           # 👈 importante
branch_labels = None
depends_on = None

def upgrade():
    op.create_unique_constraint(
        "uq_paymenthistory_payment_id",
        "payment_history",
        ["payment_id"],
    )

def downgrade():
    op.drop_constraint("uq_paymenthistory_payment_id", "payment_history", type_="unique")
