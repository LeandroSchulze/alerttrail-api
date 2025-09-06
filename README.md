# AlertTrail

FastAPI + Jinja2 + JWT. Plan Free vs Pro, historial y PDF (Pro).

## Dev rápido
```bash
uvicorn app.main:app --reload
```

## Variables de entorno
- `SECRET_KEY` (recomendado)
- `DATABASE_URL` (si usás Postgres en Render)
- `ADMIN_EMAIL`, `ADMIN_PASS`, `ADMIN_NAME`
- `FREE_DAILY_LIMIT` (opcional)

## Render
**Build**:
```bash
pip install --upgrade pip && pip install -r requirements.txt
```
**Start**:
```bash
python scripts/init_db.py && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```
**Health**: `/health`
