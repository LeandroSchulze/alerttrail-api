"""add last_verification_sent_at to users

Revision ID: add_last_verification_sent_at
Revises: <PONÉ_ACÁ_EL_ID_DE_LA_ÚLTIMA_REVISION>
Create Date: 2024-12-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# Reemplazá estos IDs según tu proyecto:
revision = "add_last_verification_sent_at"
down_revision = "<PONÉ_ACÁ_EL_ID_DE_LA_ÚLTIMA_REVISION>"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    cols = [c["name"] for c in inspector.get_columns("users")]

    if "last_verification_sent_at" not in cols:
        op.add_column(
            "users",
            sa.Column("last_verification_sent_at", sa.DateTime(), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    cols = [c["name"] for c in inspector.get_columns("users")]

    if "last_verification_sent_at" in cols:
        op.drop_column("users", "last_verification_sent_at")
