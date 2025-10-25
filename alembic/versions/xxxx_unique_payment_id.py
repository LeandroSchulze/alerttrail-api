# alembic/versions/xxxx_unique_payment_id.py
from alembic import op
import sqlalchemy as sa

# Reemplaza por tus valores
revision = "xxxx_unique_payment_id"
down_revision = "<REV_ANTERIOR>"
branch_labels = None
depends_on = None

def upgrade():
    # 1) Limpieza defensiva: quitar duplicados antes de crear el índice único
    conn = op.get_bind()
    # Encuentra payment_id duplicados y elimina filas extra, conservando la de menor rowid
    conn.exec_driver_sql("""
        DELETE FROM payment_history
        WHERE rowid NOT IN (
            SELECT MIN(rowid)
            FROM payment_history
            GROUP BY payment_id
        )
    """)
    # 2) Crear índice único (soportado en SQLite)
    op.create_index(
        "uq_paymenthistory_payment_id",
        "payment_history",
        ["payment_id"],
        unique=True,
    )

def downgrade():
    op.drop_index("uq_paymenthistory_payment_id", table_name="payment_history")
