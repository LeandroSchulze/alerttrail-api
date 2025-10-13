"""add trial fields to users

Revision ID: 20251013_add_trial_fields
Revises: 20250930_add_email_verification
Create Date: 2025-10-13

"""
from alembic import op
import sqlalchemy as sa


# Identificadores de migración
revision = "20251013_add_trial_fields"
down_revision = "20250930_add_email_verification"
branch_labels = None
depends_on = None


def upgrade():
    """Agrega los campos de trial (5 días sin cargo) al modelo User"""
    # batch_alter_table mejora compatibilidad con SQLite y cambios en caliente
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("trial_started_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("trial_expires_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("had_trial", sa.Boolean(), nullable=False, server_default=sa.text("0")))
        batch_op.add_column(sa.Column("pro_source", sa.String(length=32), nullable=True))

    # Quita el server_default una vez aplicada la migración para inserts futuros
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("had_trial", server_default=None)


def downgrade():
    """Revierte los cambios: elimina los campos de trial"""
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("pro_source")
        batch_op.drop_column("had_trial")
        batch_op.drop_column("trial_expires_at")
        batch_op.drop_column("trial_started_at")
