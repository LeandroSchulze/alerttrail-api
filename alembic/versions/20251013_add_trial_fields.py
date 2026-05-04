# alembic/versions/20251013_add_trial_fields.py
"""add trial fields to users

Revision ID: 20251013_add_trial_fields
Revises: add_email_verification_20250930
Create Date: 2025-10-13

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# Identificadores de migración
revision = "20251013_add_trial_fields"
down_revision = "add_email_verification_20250930"
branch_labels = None
depends_on = None

def upgrade():
    """Agrega los campos de trial al modelo User verificando si existen previamente"""
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    
    # Obtenemos las columnas actuales de la tabla 'users'
    columns = [c["name"] for c in inspector.get_columns("users")]

    with op.batch_alter_table("users") as batch_op:
        # Agregamos cada columna solo si NO existe en la tabla
        if "trial_started_at" not in columns:
            batch_op.add_column(sa.Column("trial_started_at", sa.DateTime(), nullable=True))
        
        if "trial_expires_at" not in columns:
            batch_op.add_column(sa.Column("trial_expires_at", sa.DateTime(), nullable=True))
            
        if "had_trial" not in columns:
            # PostgreSQL prefiere sa.false() o sa.text('false') para booleanos
            batch_op.add_column(sa.Column("had_trial", sa.Boolean(), nullable=False, server_default=sa.text("false")))
            
        if "pro_source" not in columns:
            batch_op.add_column(sa.Column("pro_source", sa.String(length=32), nullable=True))

    # Quitamos el server_default de had_trial si la columna fue creada
    # Esto asegura que el valor por defecto se gestione desde el modelo de Python
    if "had_trial" in [c["name"] for c in inspector.get_columns("users")]:
        with op.batch_alter_table("users") as batch_op:
            batch_op.alter_column("had_trial", server_default=None)

def downgrade():
    """Revierte los cambios: elimina los campos de trial"""
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("pro_source")
        batch_op.drop_column("had_trial")
        batch_op.drop_column("trial_expires_at")
        batch_op.drop_column("trial_started_at")
