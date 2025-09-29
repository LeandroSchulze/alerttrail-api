# scripts/init_db.py
import os
from datetime import datetime
from sqlalchemy import text, inspect, func
from sqlalchemy.exc import ProgrammingError, OperationalError

from app.database import engine, SessionLocal
from app.models import Base, User  # Modelos base requeridos

# Si estos modelos existen en tu repo, el import no debe romper el script
try:
    from app.models import AllowedIP, ReportDownload  # noqa: F401
except Exception:
    pass

# Aseguramos cargar Organization/OrgInvite si existen en app.models
try:
    from app.models import Organization, OrgInvite  # noqa: F401
except Exception:
    pass

try:
    from app.security import get_password_hash
except Exception:
    from app.utils.security import get_password_hash  # type: ignore


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def masked(s: str) -> str:
    if not s:
        return ""
    if "@" in s:
        name, dom = s.split("@", 1)
        return name[:2] + "***@" + dom
    return s[:2] + "***"

def truthy(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")

def _norm_email(e: str) -> str:
    return (e or "").strip().lower()

def _dialect_flags():
    dialect = engine.dialect.name  # 'sqlite', 'postgresql', etc.
    bool_true = "1" if dialect == "sqlite" else "TRUE"
    bool_false = "0" if dialect == "sqlite" else "FALSE"
    return dialect, bool_true, bool_false

def _safe_exec(sql: str):
    with engine.connect() as conn:
        try:
            conn.execute(text(sql))
            conn.commit()
        except (ProgrammingError, OperationalError) as e:
            print(f"[init_db] aviso: {e.__class__.__name__} al ejecutar: {sql}")


# ---------------------------------------------------------------------------
# Creación de tablas (idempotente)
# ---------------------------------------------------------------------------
def ensure_tables():
    try:
        import app.routers.rules  # registra UserRule y UserSetting (si existen)
    except Exception as e:
        print("[init_db] aviso: no pude registrar modelos de rules:", e)
    Base.metadata.create_all(bind=engine)
    print("[init_db] create_all OK")


# ---------------------------------------------------------------------------
# Migraciones ligeras (USERS)
# ---------------------------------------------------------------------------
def ensure_users_columns():
    insp = inspect(engine)
    dialect, BOOL_TRUE, _BOOL_FALSE = _dialect_flags()
    try:
        cols = {c["name"] for c in insp.get_columns("users")}
    except Exception:
        print("[init_db] Tabla users no existe aún (será creada por create_all)")
        return

    with engine.begin() as conn:
        if "is_active" not in cols:
            conn.execute(text(
                f"ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT {BOOL_TRUE} NOT NULL"
            ))
            print("[init_db] users.is_active agregado")

        if "plan" not in cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN plan VARCHAR(20) DEFAULT 'FREE' NOT NULL"
            ))
            print("[init_db] users.plan agregado")

        if "role" not in cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'user' NOT NULL"
            ))
            print("[init_db] users.role agregado")

        if "is_admin" not in cols:
            conn.execute(text(
                f"ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT {BOOL_TRUE if False else '0' if dialect=='sqlite' else 'FALSE'} NOT NULL"
            ))
            print("[init_db] users.is_admin agregado")

        if "is_superuser" not in cols:
            conn.execute(text(
                f"ALTER TABLE users ADD COLUMN is_superuser BOOLEAN DEFAULT {BOOL_TRUE if False else '0' if dialect=='sqlite' else 'FALSE'} NOT NULL"
            ))
            print("[init_db] users.is_superuser agregado")

        if "updated_at" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN updated_at DATETIME"))
            conn.execute(text(
                "UPDATE users SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)"
            ))
            print("[init_db] users.updated_at agregado y backfilled")

        conn.execute(text("UPDATE users SET plan = UPPER(plan)"))
        conn.execute(text("UPDATE users SET role = COALESCE(role, 'user')"))


# ---------------------------------------------------------------------------
# Migraciones ligeras (ORGANIZATIONS y ORG_INVITES)
# ---------------------------------------------------------------------------
def ensure_org_schema():
    insp = inspect(engine)
    dialect, BOOL_TRUE, BOOL_FALSE = _dialect_flags()

    try:
        _ = insp.get_columns("organizations")
    except Exception:
        Base.metadata.create_all(bind=engine)

    try:
        cols = {c["name"] for c in insp.get_columns("users")}
    except Exception:
        print("[init_db] users aún no existe; create_all lo creará")
        return

    if "org_id" not in cols:
        print("[init_db] Agregando columna users.org_id ...")
        _safe_exec("ALTER TABLE users ADD COLUMN org_id INTEGER")

    if "is_org_admin" not in cols:
        print("[init_db] Agregando columna users.is_org_admin ...")
        _safe_exec(f"ALTER TABLE users ADD COLUMN is_org_admin BOOLEAN DEFAULT {BOOL_FALSE} NOT NULL")

    if engine.dialect.name != "sqlite":
        print("[init_db] Asegurando FK users.org_id -> organizations.id ...")
        _safe_exec(
            "ALTER TABLE users "
            "ADD CONSTRAINT fk_users_org "
            "FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE SET NULL"
        )

    try:
        ocols = {c["name"] for c in insp.get_columns("organizations")}
    except Exception:
        ocols = set()

    if "seats_total" not in ocols:
        _safe_exec("ALTER TABLE organizations ADD COLUMN seats_total INTEGER DEFAULT 1 NOT NULL")
        print("[init_db] organizations.seats_total agregado")
    if "seats_used" not in ocols:
        _safe_exec("ALTER TABLE organizations ADD COLUMN seats_used INTEGER DEFAULT 0 NOT NULL")
        print("[init_db] organizations.seats_used agregado")
    if "billing_id" not in ocols:
        _safe_exec("ALTER TABLE organizations ADD COLUMN billing_id VARCHAR(255)")
        print("[init_db] organizations.billing_id agregado")

    try:
        icols = {c["name"] for c in insp.get_columns("org_invites")}
    except Exception:
        icols = set()
    if icols:
        if "token" not in icols:
            _safe_exec("ALTER TABLE org_invites ADD COLUMN token VARCHAR(64)")
            print("[init_db] org_invites.token agregado")
        if "email" not in icols:
            _safe_exec("ALTER TABLE org_invites ADD COLUMN email VARCHAR(255)")
            print("[init_db] org_invites.email agregado")
        if "used" not in icols:
            _safe_exec(f"ALTER TABLE org_invites ADD COLUMN used BOOLEAN DEFAULT {BOOL_FALSE} NOT NULL")
            print("[init_db] org_invites.used agregado")
        if "used_by_user_id" not in icols:
            _safe_exec("ALTER TABLE org_invites ADD COLUMN used_by_user_id INTEGER")
            print("[init_db] org_invites.used_by_user_id agregado")


# ---------------------------------------------------------------------------
# Migraciones ligeras (MAIL_ACCOUNTS)
# ---------------------------------------------------------------------------
def ensure_mail_accounts_columns():
    insp = inspect(engine)
    _dialect, BOOL_TRUE, _BOOL_FALSE = _dialect_flags()
    try:
        cols = {c["name"] for c in insp.get_columns("mail_accounts")}
    except Exception:
        Base.metadata.create_all(bind=engine)
        cols = {c["name"] for c in insp.get_columns("mail_accounts")}

    with engine.begin() as conn:
        if "imap_server" not in cols:
            conn.execute(text(
                "ALTER TABLE mail_accounts "
                "ADD COLUMN imap_server VARCHAR(255) DEFAULT 'imap.gmail.com' NOT NULL"
            ))
            print("[init_db] mail_accounts.imap_server agregado")
        if "imap_port" not in cols:
            conn.execute(text(
                "ALTER TABLE mail_accounts "
                "ADD COLUMN imap_port INTEGER DEFAULT 993 NOT NULL"
            ))
            print("[init_db] mail_accounts.imap_port agregado")
        if "use_ssl" not in cols:
            conn.execute(text(
                f"ALTER TABLE mail_accounts ADD COLUMN use_ssl BOOLEAN DEFAULT {BOOL_TRUE} NOT NULL"
            ))
            print("[init_db] mail_accounts.use_ssl agregado")
        if "enc_blob" not in cols:
            conn.execute(text(
                "ALTER TABLE mail_accounts ADD COLUMN enc_blob TEXT DEFAULT '' NOT NULL"
            ))
            print("[init_db] mail_accounts.enc_blob agregado")
        if "created_at" not in cols:
            conn.execute(text("ALTER TABLE mail_accounts ADD COLUMN created_at DATETIME"))
            print("[init_db] mail_accounts.created_at agregado")

        conn.execute(text(
            "UPDATE mail_accounts SET imap_server = COALESCE(imap_server, 'imap.gmail.com')"
        ))
        conn.execute(text(
            "UPDATE mail_accounts SET imap_port = COALESCE(imap_port, 993)"
        ))
        conn.execute(text(
            "UPDATE mail_accounts SET use_ssl = COALESCE(use_ssl, 1)"
        ))
        conn.execute(text(
            "UPDATE mail_accounts SET enc_blob = COALESCE(enc_blob, '')"
        ))
        conn.execute(text(
            "UPDATE mail_accounts SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP)"
        ))
        print("[init_db] mail_accounts backfill OK")


# ---------------------------------------------------------------------------
# Seed / actualización de admin
# ---------------------------------------------------------------------------
def seed_admin():
    email = _norm_email(os.getenv("ADMIN_EMAIL", "admin@alerttrail.com"))
    password = os.getenv("ADMIN_PASS") or os.getenv("ADMIN_PASSWORD") or "changeme"
    name = os.getenv("ADMIN_NAME", "Admin")
    plan = (os.getenv("ADMIN_PLAN") or "PRO").upper()
    force_reset = truthy(os.getenv("ADMIN_FORCE_RESET")) or truthy(os.getenv("ADMIN_RESET_PASSWORD"))

    db = SessionLocal()
    try:
        u = db.query(User).filter(func.lower(User.email) == email).first()

        def set_password(user, raw):
            if hasattr(user, "password_hash"):
                user.password_hash = get_password_hash(raw)
            elif hasattr(user, "hashed_password"):
                user.hashed_password = get_password_hash(raw)
            else:
                raise RuntimeError("El modelo User no tiene 'password_hash' ni 'hashed_password'.")

        if u:
            changed = False
            if (getattr(u, "role", "") or "").lower() != "admin":
                u.role = "admin"; changed = True
            if not bool(getattr(u, "is_admin", False)):
                u.is_admin = True; changed = True
            if not bool(getattr(u, "is_superuser", False)):
                u.is_superuser = True; changed = True
            if (getattr(u, "plan", "") or "").upper() != plan:
                u.plan = plan; changed = True
            if not getattr(u, "name", None):
                u.name = name; changed = True
            if hasattr(u, "is_active") and not bool(getattr(u, "is_active", True)):
                u.is_active = True; changed = True

            has_hash = getattr(u, "password_hash", None) or getattr(u, "hashed_password", None)
            if force_reset or not has_hash:
                set_password(u, password); changed = True

            if changed:
                db.add(u); db.commit()
                print(f"[init_db] admin actualizado: {masked(email)} (plan={plan})")
            else:
                print(f"[init_db] admin existe sin cambios: {masked(email)} (plan={plan})")
        else:
            u = User(email=email, name=name)
            if hasattr(u, "plan"): u.plan = plan
            if hasattr(u, "is_active"): u.is_active = True
            if hasattr(u, "role"): u.role = "admin"
            if hasattr(u, "is_admin"): u.is_admin = True
            if hasattr(u, "is_superuser"): u.is_superuser = True
            set_password(u, password)
            db.add(u); db.commit()
            print(f"[init_db] admin creado: {masked(email)} (plan={plan})")
    except Exception as e:
        db.rollback(); print(f"[init_db][ERROR] {e}"); raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Seed organización con owner_user_id
# ---------------------------------------------------------------------------
def seed_admin_org_if_requested():
    org_name = os.getenv("ADMIN_ORG_NAME", "").strip() or "Tu Empresa S.A"
    seats = int(os.getenv("ADMIN_ORG_SEATS", "25"))
    email = _norm_email(os.getenv("ADMIN_EMAIL", "admin@alerttrail.com"))

    db = SessionLocal()
    try:
        admin = db.query(User).filter(func.lower(User.email) == email).first()
        if not admin:
            print("[init_db] seed_admin_org: admin no existe todavía, saltando")
            return

        org = db.query(Organization).filter(Organization.name == org_name).first()
        if not org:
            org = Organization(
                name=org_name,
                owner_user_id=admin.id,  # <- CLAVE
                seats_total=seats,
                seats_used=0,
                billing_id=None,
                created_at=datetime.utcnow(),
            )
            db.add(org); db.flush()
            print(f"[init_db] Organización creada: {org_name} (seats_total={seats}, owner={admin.email})")
        else:
            changed = False
            if getattr(org, "owner_user_id", None) is None:
                org.owner_user_id = admin.id; changed = True
            if org.seats_total < 1:
                org.seats_total = seats; changed = True
            if changed:
                db.add(org)
                print(f"[init_db] Organización actualizada: owner={admin.email}, seats_total={org.seats_total}")

        if getattr(admin, "org_id", None) != org.id:
            admin.org_id = org.id
            admin.is_org_admin = True
            db.add(admin)

        used = db.query(User).filter(User.org_id == org.id, User.is_active == True).count()  # noqa: E712
        org.seats_used = used; db.add(org)

        db.commit()
        print(f"[init_db] seed_admin_org: admin vinculado a '{org.name}' — "
              f"seats_used={org.seats_used}/{org.seats_total}")
    except Exception as e:
        db.rollback(); print(f"[init_db][seed_admin_org ERROR] {e}")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    ensure_tables()
    ensure_users_columns()
    ensure_org_schema()
    ensure_mail_accounts_columns()
    seed_admin()
    seed_admin_org_if_requested()
    print("[init_db] OK")


if __name__ == "__main__":
    main()
