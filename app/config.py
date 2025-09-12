# app/config.py
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    # Auth
    SECRET_KEY: str = Field(default="devsecret")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60 * 24 * 7)  # 7 días

    # Infra
    DATABASE_URL: str = Field(default="sqlite:////var/data/alerttrail.sqlite3")
    REPORTS_DIR: str = Field(default="/var/data/reports")

    # Admin seed
    ADMIN_EMAIL: str | None = None
    ADMIN_PASS: str | None = None
    ADMIN_NAME: str | None = "Admin"
    ADMIN_FORCE_RESET: bool = False

    class Config:
        env_file = ".env"
        extra = "ignore"

_settings: Settings | None = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # Carga de variables de entorno
    return _settings
