# AlertTrail API

FastAPI con Dashboard (Log Scanner + PDF) y Mail Scanner (trial 5 días, luego PRO).

## Endpoints clave
- `/` landing / dashboard
- `/dashboard` UI
- `/health` healthcheck para Render
- `/docs` Swagger
- `/auth/login`, `/auth/me`
- `/analysis/generate_pdf` → devuelve `{ "url": "/reports/..." }`
- `/reports` lista de PDFs

## Deploy en Render (desde GitHub)
1. Conecta el repo a Render → **New Web Service**.
2. Render detectará `render.yaml`. Aceptá.
3. Variables ya vienen en el manifest (podés editarlas en Settings).
4. Primer arranque: corre `scripts/init_db.py` y luego `uvicorn`.

## Variables recomendadas
- `PYTHON_VERSION=3.11`
- `JWT_SECRET` (auto)
- `ADMIN_EMAIL`, `ADMIN_PASS`, `ADMIN_NAME`
- Opcionales: `DATABASE_URL` (SQLite en `/var/data/alerttrail.sqlite3`), `FERNET_SECRET`, `MAIL_CRON_SECRET`.

## Usuarios testers
- Iniciar sesión con `ADMIN_EMAIL` / `ADMIN_PASS` o creá usuarios en el dashboard/admin.
