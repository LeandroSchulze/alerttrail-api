# app/database.py
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 1. Obtenemos la variable de Railway
db_url = os.getenv("DATABASE_URL")

if db_url:
    # 2. Corregimos el prefijo (Railway usa postgres:// y SQLAlchemy requiere postgresql://)
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    
    # Limpieza de espacios por seguridad
    db_url = db_url.strip()
    
    # Configuramos el motor para PostgreSQL
    engine = create_engine(db_url)
    print("✅ Conectado a PostgreSQL en Railway")
else:
    # 3. Fallback solo si no hay variable (Desarrollo local)
    print("⚠️ DATABASE_URL no encontrada. Usando SQLite local.")
    db_url = "sqlite:///./alerttrail.db"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- NUEVA FUNCIÓN PARA SINCRONIZAR TABLAS ---
def init_db():
    """
    Crea las tablas en la base de datos si no existen.
    Esto solucionará el error 'relation push_subscriptions does not exist'.
    """
    import app.models # Importante importar los modelos para que Base los vea
    Base.metadata.create_all(bind=engine)
    print("🚀 Base de datos: Tablas sincronizadas (si faltaba alguna, ya fue creada).")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
