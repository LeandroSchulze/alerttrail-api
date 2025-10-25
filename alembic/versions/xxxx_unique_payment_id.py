# alembic/versions/xxxx_unique_payment_id.py
from alembic import op
import sqlalchemy as sa

# Mantener este ID porque el merge lo usa
revision = "xxxx_unique_payment_id"
# Este es el padre correcto para crear la segunda rama
down_revision = "add_email_verification_20250930"
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()

    # 1) Limpieza defensiva: eliminar duplicados SOLO donde provider_payment_id NO es NULL
    #    Conserva la fila con menor rowid por (provider, provider_payment_id)
    conn.exec_driver_sql("""
        DELETE FROM payments_history
        WHERE provider_payment_id IS NOT NULL
          AND rowid NOT IN (
              SELECT MIN(rowid)
              FROM payments_history
              WHERE provider_payment_id IS NOT NULL
              GROUP BY provider, provider_payment_id
          )
    """)

    # 2) Índice único compatible con SQLite sobre (provider, provider_payment_id)
    op.create_index(
        "uq_payments_history_provider_pid",
        "payments_history",
        ["provider", "provider_payment_id"],
        unique=True,
    )

def downgrade():
    op.drop_index("uq_payments_history_provider_pid", table_name="payments_history")
