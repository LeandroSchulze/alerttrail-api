# app/db_hotfix.py
from .database import SessionLocal

def ensure_user_pro_columns() -> dict:
    """
    Asegura columnas en 'users':
      - pro_expires_at (DateTime / TIMESTAMP)
      - last_payment_id (VARCHAR(64))
    Idempotente. Funciona en SQLite y Postgres.
    """
    out = {"dialect": None, "created": [], "existing": [], "notes": []}
    db = SessionLocal()
    try:
        engine = db.get_bind()
        dialect = engine.dialect.name
        out["dialect"] = dialect

        with engine.connect() as conn:
            if dialect == "sqlite":
                # --- Detectar columnas existentes
                cols = set()
                for row in conn.exec_driver_sql("PRAGMA table_info(users)"):
                    # row = (cid, name, type, notnull, dflt_value, pk)
                    cols.add(row[1])

                # Si no existe la tabla, no hacemos nada (la creará SQLAlchemy en otro momento)
                if not cols and conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
                ).fetchone() is None:
                    out["notes"].append("users table not found (skip)")
                    return out

                # --- Agregar columnas con COMMIT explícito
                if "pro_expires_at" in cols:
                    out["existing"].append("pro_expires_at")
                else:
                    with conn.begin():
                        conn.exec_driver_sql("ALTER TABLE users ADD COLUMN pro_expires_at DATETIME")
                    out["created"].append("pro_expires_at")

                if "last_payment_id" in cols:
                    out["existing"].append("last_payment_id")
                else:
                    with conn.begin():
                        conn.exec_driver_sql("ALTER TABLE users ADD COLUMN last_payment_id VARCHAR(64)")
                    out["created"].append("last_payment_id")

            else:
                # Postgres / otros dialectos
                with conn.begin():
                    conn.exec_driver_sql(
                        "ALTER TABLE IF EXISTS users "
                        "ADD COLUMN IF NOT EXISTS pro_expires_at TIMESTAMP NULL"
                    )
                out["created"].append("pro_expires_at-or-existing")

                with conn.begin():
                    conn.exec_driver_sql(
                        "ALTER TABLE IF EXISTS users "
                        "ADD COLUMN IF NOT EXISTS last_payment_id VARCHAR(64) NULL"
                    )
                out["created"].append("last_payment_id-or-existing")

        return out
    finally:
        db.close()

def inspect_user_columns() -> dict:
    """Devuelve las columnas actuales de 'users' (útil para diagnóstico)."""
    db = SessionLocal()
    try:
        engine = db.get_bind()
        dialect = engine.dialect.name
        cols = []
        with engine.connect() as conn:
            if dialect == "sqlite":
                for row in conn.exec_driver_sql("PRAGMA table_info(users)"):
                    cols.append({"name": row[1], "type": row[2], "notnull": row[3], "default": row[4], "pk": row[5]})
            else:
                q = """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'users'
                ORDER BY ordinal_position
                """
                for name, typ, nullable in conn.exec_driver_sql(q):
                    cols.append({"name": name, "type": typ, "nullable": nullable})
        return {"dialect": dialect, "columns": cols}
    finally:
        db.close()
