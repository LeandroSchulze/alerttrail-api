# alembic/versions/20251013_add_trial_fields.py
from alembic import op
import sqlalchemy as sa

revision = "20251013_add_trial_fields"
down_revision = "add_email_verification_20250930"
branch_labels = None
depends_on = None

def upgrade():
    # Usamos SQL directo para aprovechar el "IF NOT EXISTS" de Postgres
    # Esto es mucho más robusto que el Inspector en entornos de producción
    op.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMP WITHOUT TIME ZONE')
    op.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_expires_at TIMESTAMP WITHOUT TIME ZONE')
    op.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS had_trial BOOLEAN DEFAULT FALSE')
    op.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS pro_source VARCHAR(32)')
    
    # Aseguramos que had_trial no sea null si la columna ya existía o se acaba de crear
    op.execute('UPDATE users SET had_trial = FALSE WHERE had_trial IS NULL')
    op.execute('ALTER TABLE users ALTER COLUMN had_trial SET NOT NULL')

def downgrade():
    op.drop_column("users", "pro_source")
    op.drop_column("users", "had_trial")
    op.drop_column("users", "trial_expires_at")
    op.drop_column("users", "trial_started_at")
