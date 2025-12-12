import os
import sys

# Asegura que la raíz del proyecto (donde está la carpeta `app`) esté en sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from datetime import datetime, timedelta, timezone


from sqlalchemy import inspect, text, func
from sqlalchemy.exc import OperationalError

from app.database import engine, SessionLocal, Base
from app.security import get_password_hash

# Ajustá este import según tu estructura real de modelos.
# Si tenés submódulos, algo como:
#   from app.models.user import User
#   from app.models.mail import MailAccount
#   ...
from app.models import (
    User,
    MailAccount,
    OrgInvite,
    PaymentEvent,
    PaymentHistory,
)


# ---------------------------------------------------------------------------
# Helpers básicos
# ---------------------------------------------------------------------------

def ensure_tables() -> None:
    """Crea todas las tablas definidas en los modelos si no existen."""
    Base.metadata.create_all(bind=engine)
    print("[init_db] create_all OK")


def ensure_org_invites_columns() -> None:
    """
    Asegura columnas nuevas en org_invites:
    - invited_by_id
    - accepted_at
    - expires_at

    Es idempotente: si ya existen, no hace nada.
    """
    insp = inspect(engine)
    try:
        cols = {c["name"] for c in insp.get_columns("org_invites")}
    except Exception:
        print("[init_db] Tabla org_invites no existe aún (será creada por create_all)")
        return

    with engine.begin() as conn:
        if "invited_by_id" not in cols:
            conn.execute(
                text("ALTER TABLE org_invites ADD COLUMN invited_by_id INTEGER")
            )
            print("[init_db] org_invites.invited_by_id agregado")

        if "accepted_at" not in cols:
            conn.execute(
                text("ALTER TABLE org_invites ADD COLUMN accepted_at DATETIME")
            )
            print("[init_db] org_invites.accepted_at agregado")

        if "expires_at" not in cols:
            conn.execute(
                text("ALTER TABLE org_invites ADD COLUMN expires_at DATETIME")
            )
            print("[init_db] org_invites.expires_at agregado")


def ensure_payment_events_columns() -> None:
    """
    Asegura columnas nuevas en payment_events:
    - event_type
    - processed_at

    Es idempotente: si ya existen, no hace nada.
    """
    insp = inspect(engine)
    try:
        cols = {c["name"] for c in insp.get_columns("payment_events")}
    except Exception:
        print("[init_db] Tabla payment_events no existe aún (será creada por create_all)")
        return

    with engine.begin() as conn:
        if "event_type" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE payment_events "
                    "ADD COLUMN event_type VARCHAR(50) NOT NULL DEFAULT 'created'"
                )
            )
            print("[init_db] payment_events.event_type agregado")

        if "processed_at" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE payment_events "
                    "ADD COLUMN processed_at DATETIME"
                )
            )
            print("[init_db] payment_events.processed_at agregado")


from sqlalchemy import inspect, text  # asegúrate de tener estos imports arriba del archivo

def ensure_payments_history_columns():
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if "payments_history" not in tables:
        return

    cols = {c["name"] for c in inspector.get_columns("payments_history")}

    with engine.begin() as conn:
        if "external_payment_id" not in cols:
            conn.execute(text(
                "ALTER TABLE payments_history "
                "ADD COLUMN external_payment_id VARCHAR(255)"
            ))
            print("[init_db] payments_history.external_payment_id agregado")

        if "months" not in cols:
            conn.execute(text(
                "ALTER TABLE payments_history "
                "ADD COLUMN months INTEGER DEFAULT 1"
            ))
            print("[init_db] payments_history.months agregado")

        if "amount" not in cols:
            conn.execute(text(
                "ALTER TABLE payments_history "
                "ADD COLUMN amount REAL DEFAULT 0"
            ))
            print("[init_db] payments_history.amount agregado")

        if "currency" not in cols:
            conn.execute(text(
                "ALTER TABLE payments_history "
                "ADD COLUMN currency VARCHAR(10)"
            ))
            print("[init_db] payments_history.currency agregado")

        if "status" not in cols:
            conn.execute(text(
                "ALTER TABLE payments_history "
                "ADD COLUMN status VARCHAR(50)"
            ))
            print("[init_db] payments_history.status agregado")

        if "description" not in cols:
            conn.execute(text(
                "ALTER TABLE payments_history "
                "ADD COLUMN description TEXT"
            ))
            print("[init_db] payments_history.description agregado")

        if "raw_payload" not in cols:
            conn.execute(text(
                "ALTER TABLE payments_history "
                "ADD COLUMN raw_payload TEXT"
            ))
            print("[init_db] payments_history.raw_payload agregado")




def backfill_mail_accounts() -> None:
    """
    Backfill muy conservador para mail_accounts.

    Ahora mismo solo imprime OK para no romper nada ni disparar
    queries que arrastren relaciones raras.
    Si en el futuro querés lógica más compleja, se puede agregar acá.
    """
    print("[init_db] mail_accounts backfill OK")


# ---------------------------------------------------------------------------
# Seed de usuario admin
# ---------------------------------------------------------------------------

def seed_admin() -> None:
    """
    Crea o actualiza el usuario admin usando variables de entorno:

    - ADMIN_EMAIL (obligatorio)
    - ADMIN_PASS  (obligatorio)
    - ADMIN_NAME  (opcional, default "AlertTrail Admin")
    - ADMIN_FORCE_RESET = "1" / "true" / "yes" / "on" para forzar reset de pass
    """
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASS")
    name = os.getenv("ADMIN_NAME", "AlertTrail Admin")

    if not email or not password:
        print("[init_db] ADMIN_EMAIL o ADMIN_PASS no configurados, no se crea admin")
        return

    email_norm = email.strip().lower()
    force_reset_raw = os.getenv("ADMIN_FORCE_RESET", "").strip().lower()
    force_reset = force_reset_raw in ("1", "true", "yes", "on")

    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .filter(func.lower(User.email) == email_norm)
            .first()
        )

        if not user:
            # Crear admin nuevo
            user = User(
                email=email_norm,
                name=name,
                is_admin=True,
            )
            user.hashed_password = get_password_hash(password)

            # Por comodidad, dejarlo PRO un año
            try:
                # Si el modelo tiene estos campos, los seteamos
                user.is_pro = True
                user.pro_expires_at = datetime.now(timezone.utc) + timedelta(days=365)
            except AttributeError:
                # Si el modelo no tiene esos atributos, lo ignoramos
                pass

            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"[init_db] Admin creado con id={user.id}, email={user.email}")
            return

        # Ya existe un admin con ese email
        changed = False

        if not getattr(user, "is_admin", False):
            user.is_admin = True
            changed = True

        if force_reset:
            user.hashed_password = get_password_hash(password)
            changed = True

        # Opcionalmente refrescamos PRO
        try:
            if not getattr(user, "is_pro", False):
                user.is_pro = True
                changed = True
            if getattr(user, "pro_expires_at", None) is None:
                user.pro_expires_at = datetime.now(timezone.utc) + timedelta(days=365)
                changed = True
        except AttributeError:
            pass

        if changed:
            db.add(user)
            db.commit()
            print(f"[init_db] Admin actualizado id={user.id}, email={user.email}")
        else:
            print(f"[init_db] Admin ya existía y no requería cambios (id={user.id})")

    except OperationalError as e:
        print(f"[init_db][ERROR] OperationalError al hacer seed_admin: {e}")
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Orden importante:

    1) create_all: crea tablas base si no existen.
    2) ensure_*_columns: pequeñas "migraciones" con ALTER TABLE.
       Esto se hace ANTES de tocar User para evitar errores
       tipo "no such column ..." al cargar relaciones.
    3) backfill_mail_accounts: tareas adicionales.
    4) seed_admin: crea/actualiza el admin.
    """
    ensure_tables()

    # Migraciones ligeras
    ensure_org_invites_columns()
    ensure_payment_events_columns()
    ensure_payments_history_columns()

    # Tareas de backfill
    backfill_mail_accounts()

    # Crear/actualizar admin
    seed_admin()

    print("[init_db] done")


if __name__ == "__main__":
    main()
