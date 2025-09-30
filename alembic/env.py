# alembic/env.py
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# --- Alembic Config ---
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# === Database URL desde ENV (Render) con fallback a SQLite ===
db_url = os.getenv("DATABASE_URL", "sqlite:////var/data/alerttrail.sqlite3").strip()

# Normaliza postgres:// -> postgresql:// (SQLAlchemy)
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# Expone a Alembic como sqlalchemy.url (lo estándar)
config.set_main_option("sqlalchemy.url", db_url)

# --- Metadata objetivo ---
# Importá tu Base aquí para que Alembic “vea” los modelos
from app.models import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Modo offline: genera SQL sin conectarse."""
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Modo online: se conecta y ejecuta migraciones."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",              # 👈 clave: usa *sqlalchemy.* y no ""
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
