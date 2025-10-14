# app/db_hotfix.py
from sqlalchemy import text
from .database import SessionLocal

def ensure_user_pro_columns() -> dict:
    """
    Crea users.pro_expires_at (DateTime) y users.last_payment_id (VARCHAR(64))
    si no existen. Funciona en SQLite y Postgres. Idempotente.
    Devuelve un dict con lo hecho para log/debug.
    """
    out = {"dialect": None, "created": [], "existing": []}
    db = SessionLocal()
    try:
        engine = db.get_bind()
        dialect = engine.dialect.name
        out["dialect"] = dialect

        with engine.connect() as conn:
            if dialect == "sqlite":
                # Descubrir columnas actuales
                cols = set()
                for row in conn.exec_driver_sql("PRAGMA table_info(users)"):
                    # row: (cid, name, type, notnull, dflt_value, pk)
                    cols.add(row[1])

                if "pro_expires_at" in cols:
                    out["existing"].append("pro_expires_at")
                else:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN pro_expires_at DATETIME")
                    out["created"].append("pro_expires_at")

                if "last_payment_id" in cols:
                    out["existing"].append("last_payment_id")
                else:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN last_payment_id VARCHAR(64)")
                    out["created"].append("last_payment_id")

            else:
                # Postgres / otros
                conn.exec_driver_sql(
                    "ALTER TABLE IF EXISTS users "
                    "ADD COLUMN IF NOT EXISTS pro_expires_at TIMESTAMP NULL"
                )
                out["created"].append("pro_expires_at-or-existing")

                conn.exec_driver_sql(
                    "ALTER TABLE IF EXISTS users "
                    "ADD COLUMN IF NOT EXISTS last_payment_id VARCHAR(64) NULL"
                )
                out["created"].append("last_payment_id-or-existing")

        return out
    finally:
        db.close()
