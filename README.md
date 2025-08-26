
# AlertTrail

App de análisis de logs con FastAPI + Jinja2.
Listo para desplegar en Render y que testers puedan probarlo.

## Características
- Login con JWT (registro opcional)
- Dashboard con nombre del usuario
- Historial de análisis con filtros de fecha
- Exportar PDF (plan Pro) y logo genérico
- Panel de perfil (cambiar contraseña, ver plan)
- Panel admin (descargas mensuales, cuentas Pro)
- Multilenguaje (es/en) básico
- Endpoint `/health` para Render

## Estructura
```
app/
  main.py
  config.py
  database.py
  models.py
  schemas.py
  auth.py
  deps.py
  services/
    analysis.py
    pdf.py
    i18n.py
  routers/
    auth.py
    dashboard.py
    analysis.py
    profile.py
    settings.py
    admin.py
templates/
  base.html, *.html
static/
  css/tailwind.css
  img/logo.png
scripts/
  init_db.py
```
## Variables de entorno
- `ADMIN_EMAIL`, `ADMIN_PASS`, `ADMIN_NAME`
- `SECRET_KEY` (opcional, se genera una por defecto)
- `PYTHON_VERSION` (para Render)
- `DATABASE_URL` (opcional; si no se define, usa SQLite en `/var/data/alerttrail.sqlite3` en Render o `./alerttrail.sqlite3` local)
- `DEFAULT_LANGUAGE` (`es` o `en`)

## Comandos para Render
**Build Command**
```
pip install --upgrade pip && pip install -r requirements.txt
```

**Start Command**
```
python scripts/init_db.py && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

**Health check**
`/health`

> Recuerda crear las variables: `ADMIN_EMAIL`, `ADMIN_PASS`, `ADMIN_NAME`, `PYTHON_VERSION` y opcional `DATABASE_URL`.
