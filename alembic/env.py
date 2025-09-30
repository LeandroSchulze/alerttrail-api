import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Config Alembic
config = context.config

# Loggers de alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No usamos autogenerate ni target_metadata; ejecutamos scripts "a mano"
target_metadata = None

def get_url():
    # Prioriza ENV (Render: DATABASE_URL)
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    # Si quisieras fallback, ponelo aquí
    raise RuntimeError("DATABASE_URL no está definido")

def run_migrations_offline():
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    ini_section = config.get_section(config.config_ini_section) or {}
    ini_section["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        ini_section,
        prefix="",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
