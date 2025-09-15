# scripts/init_db.py
import os, sys
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from app.database import Base, engine, SessionLocal
from app.security import get_password_hash
from app.models import User

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip()
ADMIN_PASS  = os.getenv("ADMIN_PASS", "").strip()
ADMIN_NAME  = os.getenv("ADMIN_NAME", "Admin").strip()
ADMIN_FORCE_RESET = os.getenv("ADMIN_FORCE_RESET","false").lower() in {"1","true","yes"}

REQUIRED_COLUMNS = {
    "name": ("TEXT", "''"),
    "email": ("TEXT", "''"),
    "plan": ("TEXT", "'FREE'"),
    "is_active": ("BOOLEAN", "1"),
    "password_hash": ("TEXT", "''"),
    "hashed_password": ("TEXT", "''"),
}

def ensure_env():
    miss = []
    if not ADMIN_EMAIL: miss.append("ADMIN_EMAIL")
    if not ADMIN_PASS:  miss.append("ADMIN_PASS")
    if miss:
        print(f"[init_db] Faltan variables: {', '.join(miss)}", file=sys.stderr)
        sys.exit(1)

def _sqlite_get_columns(conn, table: str):
    rows = conn.execute(text(f"PRAGMA table_info({table});"))
    return {row[1] for row in rows}

def _pg_has_column(conn, table: str, col: str):
    q = text("""SELECT 1 FROM information_schema.columns
                WHERE table_name=:t AND column_name=:c LIMIT 1""")
    return conn.execute(q, {"t": table, "c": col}).scalar() is not None

def ensure_users_table_and_columns():
    with engine.begin() as conn:
        dialect = conn.dialect.name
        Base.metadata.create_all(bind=engine)
        if dialect == "sqlite":
            existing = _sqlite_get_columns(conn, "users")
            for col, (ctype, default_expr) in REQUIRED_COLUMNS.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ctype} DEFAULT {default_expr};"))
                    print(f"[init_db] SQLite: columna users.{col} creada")
        else:
            for col, (ctype, default_expr) in REQUIRED_COLUMNS.items():
                if not _pg_has_column(conn, "users", col):
                    pg_type = {"TEXT":"TEXT","BOOLEAN":"BOOLEAN"}.get(ctype, ctype)
                    default_sql = "DEFAULT TRUE" if (pg_type=="BOOLEAN" and default_expr in ("1","TRUE")) else f"DEFAULT {default_expr}"
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {pg_type} {default_sql};"))
                    print(f"[init_db] PG: columna users.{col} creada")
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email_unique ON users(email);"))
        print("[init_db] Índice único en users.email OK")

def set_if_hasattr(obj, field, value):
    if hasattr(obj, field):
        try: setattr(obj, field, value)
        except Exception: pass

def upsert_admin():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if user is None:
            user = User(name=ADMIN_NAME or "Admin", email=ADMIN_EMAIL, plan="PRO", is_active=True)
            pwd = get_password_hash(ADMIN_PASS)
            if hasattr(user, "password_hash"):   user.password_hash = pwd
            if hasattr(user, "hashed_password"): user.hashed_password = pwd
            set_if_hasattr(user, "role", "admin")
            set_if_hasattr(user, "is_admin", True)
            db.add(user); db.commit()
            print(f"[init_db] Admin creado: {ADMIN_EMAIL} (plan=PRO)")
        else:
            changed = False
            if ADMIN_FORCE_RESET:
                pwd = get_password_hash(ADMIN_PASS)
                if hasattr(user, "password_hash"):   user.password_hash = pwd; changed = True
                if hasattr(user, "hashed_password"): user.hashed_password = pwd; changed = True
            if getattr(user, "plan", "FREE") != "PRO":
                user.plan = "PRO"; changed = True
            if hasattr(user, "is_active") and not getattr(user, "is_active"):
                user.is_active = True; changed = True
            if ADMIN_NAME and getattr(user, "name","") != ADMIN_NAME:
                user.name = ADMIN_NAME; changed = True
            if hasattr(user, "role") and getattr(user, "role", None) != "admin":
                user.role = "admin"; changed = True
            if hasattr(user, "is_admin") and getattr(user, "is_admin", None) is not True:
                user.is_admin = True; changed = True
            if changed:
                db.add(user); db.commit()
                print(f"[init_db] Admin actualizado: {ADMIN_EMAIL} (plan=PRO)")
            else:
                print(f"[init_db] Admin ya estaba OK: {ADMIN_EMAIL} (plan=PRO)")
    finally:
        db.close()

def main():
    ensure_env()
    try:
        ensure_users_table_and_columns()
    except OperationalError as e:
        print(f"[init_db] Error al asegurar esquema: {e}", file=sys.stderr)
        sys.exit(1)
    upsert_admin()

if __name__ == "__main__":
    main()
