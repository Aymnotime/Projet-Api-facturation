"""Configuration centralisée et validée de l'application.

Toutes les variables d'environnement sont déclarées, typées et validées via
pydantic-settings. En mode production (``ENVIRONMENT=production``) :

* un ``JWT_SECRET`` explicite est obligatoire (pas de secret généré aléatoire) ;
* les valeurs par défaut "dev" (mot de passe Postgres ``billing``, CORS ouvert)
  sont refusées ;
* le schéma de base SQLite est interdit.

L'instance est exposée via ``get_settings()`` (cachée) et peut être invalidée
dans les tests avec ``settings_clear_cache()``.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Général -----------------------------------------------------------
    app_name: str = "Projet API Facturation"
    environment: Environment = "development"
    debug: bool = False

    # --- Base de données ---------------------------------------------------
    database_url: str = "sqlite:///./billing.db"

    # --- Sécurité / JWT ----------------------------------------------------
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=90)
    api_key_prefix_length: int = Field(default=16, ge=4, le=64)

    # --- CORS --------------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value):
        """Accepte une liste JSON ou une chaîne CSV dans la variable d'env."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    # --- Redis / Rate limiting ---------------------------------------------
    redis_url: str | None = None
    rate_limit_enabled: bool = True
    rate_limit_requests: int = Field(default=120, ge=1, description="Requêtes / fenêtre")
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_strict_enabled: bool = True
    rate_limit_strict_requests: int = Field(default=10, ge=1)
    rate_limit_strict_window_seconds: int = Field(default=60, ge=1, le=3600)

    # --- Celery ------------------------------------------------------------
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    @model_validator(mode="after")
    def _validate_production_hardening(self) -> "Settings":
        if self.environment != "production":
            return self
        errors: list[str] = []
        if not self.jwt_secret or self.jwt_secret in {"change-me", "secret", "dev-secret"}:
            errors.append("JWT_SECRET must be explicitly set in production")
        if self.database_url.startswith("sqlite"):
            errors.append("SQLite is not allowed in production (DATABASE_URL)")
        if "*" in self.cors_origins:
            errors.append("CORS_ORIGINS must not contain '*' in production")
        if "billing:billing@" in self.database_url:
            errors.append("Default dev credentials (billing/billing) forbidden in production")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def async_processing_enabled(self) -> bool:
        """Celery/Factur-X asynchrone uniquement si Redis est configuré."""
        return bool(self.redis_url or self.celery_broker_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def settings_clear_cache() -> None:
    get_settings.cache_clear()
