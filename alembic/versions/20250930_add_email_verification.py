"""add email verification fields to users"""

from alembic import op
import sqlalchemy as sa

# Primera migración manual → sin historial previo
revision = "add_email_verification_20250930"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("verification_code", sa.String(length=12), nullable=True))
        batch.add_column(sa.Column("verification_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("verification_attempts", sa.Integer(), nullable=False, server_default="0"))

    # ⚠️ Si usás SQLite, COMENTÁ estas dos líneas (SQLite no soporta ALTER COLUMN DROP DEFAULT)
    # op.execute("ALTER TABLE users ALTER COLUMN email_verified DROP DEFAULT")
    # op.execute("ALTER TABLE users ALTER COLUMN verification_attempts DROP DEFAULT")

def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_column("verification_attempts")
        batch.drop_column("verification_expires_at")
        batch.drop_column("verification_code")
        batch.drop_column("email_verified")
