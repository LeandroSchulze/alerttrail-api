import os
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    APP_NAME: str = "AlertTrail"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change_this_secret")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # Admin bootstrap (pueden quedar así para test)
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "admin@example.com")
    ADMIN_PASS: str = os.getenv("ADMIN_PASS", "admin1234")
    ADMIN_NAME: str = os.getenv("ADMIN_NAME", "Admin")

    FREE_DAILY_LIMIT: int = int(os.getenv("FREE_DAILY_LIMIT", "10"))

    # DB: usa env si existe; si no, fuerza /tmp (siempre escribible en Render)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:////tmp/alerttrail.sqlite3")

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings() -> Settings:
    return Settings()
