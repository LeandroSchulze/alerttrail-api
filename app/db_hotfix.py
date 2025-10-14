# app/db_hotfix.py
from contextlib import closing
from sqlalchemy import text
from .database import SessionLocal

def ensure_user_pro_columns() -> None:
    """
    Crea columnas users.pro_expires_at y users.last_payment_id si no existen.
    Soporta SQLite y Postgres. Idempotente.
    """
    db = SessionLocal()
    try:
        engine = db.get_bind()
        dialect = engine.dialect.name

        with engine.connect() as conn:
            if dialect == "sqlite":
                # Descubrir columnas actuales
                cols = set()
                for row in conn.exec_driver_sql("PRAGMA table_info(users)"):
                    cols.add(row[1])  # name

                if "pro_expires_at" not in cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN pro_expires_at DATETIME")

                if "last_payment_id" not in cols:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN last_payment_id VARCHAR(64)")

            else:
                # Postgres / otros: usar IF NOT EXISTS
                conn.exec_driver_sql(
                    "ALTER TABLE IF EXISTS users "
                    "ADD COLUMN IF NOT EXISTS pro_expires_at TIMESTAMP NULL"
                )
                conn.exec_driver_sql(
                    "ALTER TABLE IF EXISTS users "
                    "ADD COLUMN IF NOT EXISTS last_payment_id VARCHAR(64) NULL"
                )
    finally:
        db.close()
