from alembic import op
import sqlalchemy as sa

# Revisión actual
revision = "xxxx_unique_payment_id"

# Reemplazá ESTE valor por el id real del último migration que ya tenías
down_revision = "REV_ANTERIOR"


# Etiquetas opcionales (no es necesario tocarlas)
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_paymenthistory_payment_id",
        "payment_history",
        ["payment_id"],
    )


def downgrade():
    op.drop_constraint(
        "uq_paymenthistory_payment_id",
        "payment_history",
        type_="unique",
    )
