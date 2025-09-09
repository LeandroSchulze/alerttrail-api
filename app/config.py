import os
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    APP_NAME: str = "AlertTrail"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change_this_secret")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "admin@tudominio.com")
    ADMIN_PASS: str = os.getenv("ADMIN_PASS", "Cambiar123!")
    ADMIN_NAME: str = os.getenv("ADMIN_NAME", "Admin")

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:////tmp/alerttrail.sqlite3")
    REPORTS_DIR: str = os.getenv("REPORTS_DIR", "/tmp/reports")

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings() -> Settings:
    return Settings()
