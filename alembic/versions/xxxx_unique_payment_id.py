# alembic/versions/xxxx_unique_payment_id.py
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# Mantener este ID porque el merge lo usa
revision = "xxxx_unique_payment_id"
# Este es el padre correcto para crear la segunda rama
down_revision = "add_email_verification_20250930"
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    tables = inspector.get_table_names()

    # 1) Asegurar que la columna existe en PostgreSQL
    # Si la columna no está, la creamos antes de intentar poner el índice
    if "payments_history" in tables:
        columns = [c["name"] for c in inspector.get_columns("payments_history")]
        if "provider_payment_id" not in columns:
            op.add_column("payments_history", sa.Column("provider_payment_id", sa.String(), nullable=True))

    # 2) Eliminar el bloque DELETE manual que usaba 'rowid'
    # En PostgreSQL no es necesario para una base de datos nueva 
    # y el uso de 'rowid' rompe la ejecución en Railway.

    # 3) Crear el índice único sobre (provider, provider_payment_id)
    # Se eliminan índices previos si existen para evitar conflictos
    existing_indexes = inspector.get_indexes("payments_history")
    if not any(idx["name"] == "uq_payments_history_provider_pid" for idx in existing_indexes):
        op.create_index(
            "uq_payments_history_provider_pid",
            "payments_history",
            ["provider", "provider_payment_id"],
            unique=True,
        )

def downgrade():
    op.drop_index("uq_payments_history_provider_pid", table_name="payments_history")
