"""Application settings loaded from environment variables (.env).

Uses pydantic-settings so every value is validated and typed. Never hardcode
secrets here — provide them through the environment / .env file.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    APP_NAME: str = "AN-NOUR API"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # --- Server ---
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = True

    # --- Logging ---
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # --- Database (MySQL) ---
    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = ""
    MYSQL_DATABASE: str = "business_flow_suite"
    DATABASE_URL: str | None = None
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 1800

    # --- Security / JWT ---
    SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION_use_a_long_random_value"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- Localisation ---
    DEFAULT_COUNTRY_CODE: str = "224"

    # --- Email (SMTP) ---
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USE_SSL: bool = True
    SMTP_USE_TLS: bool = False
    EMAIL: str = ""
    EMAIL_PASS: str = ""
    EMAIL_FROM_NAME: str = "AN-NOUR"

    # --- One-time passwords (email verification) ---
    OTP_LENGTH: int = 6
    OTP_EXPIRE_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RESEND_COOLDOWN_SECONDS: int = 60

    # --- Password reset (email link) ---
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30
    PASSWORD_RESET_RESEND_COOLDOWN_SECONDS: int = 60

    # --- Seed (first super-admin created by `poetry run seed`) ---
    FIRST_SUPERADMIN_EMAIL: str = "admin@bfs.local"
    FIRST_SUPERADMIN_PASSWORD: str = "Admin@1234"
    FIRST_SUPERADMIN_FIRSTNAME: str = "Super"
    FIRST_SUPERADMIN_LASTNAME: str = "Admin"

    # --- Frontend ---
    FRONTEND_URL: str = "http://localhost:8080"

    # --- CORS ---
    BACKEND_CORS_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost:8080",
        "http://localhost:3000",
    ]

    # --- File storage (Cloudinary) ---
    FILE_STORAGE_BACKEND: str = "cloudinary"
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""
    CLOUDINARY_FOLDER: str = "lamahetvous"
    UPLOAD_MAX_BYTES: int = 10_485_760  # 10 MB

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    # ── Computed fields ───────────────────────────────────────────────────────

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_database_uri(self) -> str:
        """Async SQLAlchemy connection string (aiomysql driver)."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        password = f":{self.MYSQL_PASSWORD}" if self.MYSQL_PASSWORD else ""
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}{password}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}?charset=utf8mb4"
        )

    @property
    def cloudinary_configured(self) -> bool:
        """True only when all three Cloudinary credentials are set."""
        return bool(
            self.CLOUDINARY_CLOUD_NAME and self.CLOUDINARY_API_KEY and self.CLOUDINARY_API_SECRET
        )

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
