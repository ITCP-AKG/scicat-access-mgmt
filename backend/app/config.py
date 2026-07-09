"""Application settings (T005)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


# SciCat special / reserved group strings that must never be created as managed groups.
DEFAULT_RESERVED_GROUPS = [
    "admin",
    "globalaccess",
    "all",
    "ingestor",
    "archivemanager",
    "proposalingestor",
    "sampleingestor",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Storage ---
    app_mongo_uri: str = "mongodb://localhost:27017"
    app_db_name: str = "scicat_access_mgmt"
    # SciCat's own database (projection + directory source).
    scicat_mongo_uri: str = "mongodb://localhost:27017"
    scicat_db_name: str = "dacat"
    scicat_identity_collection: str = "UserIdentity"

    # --- SciCat REST ---
    scicat_base_url: str = "http://localhost:80/api/v3"

    # --- Auth ---
    # Optional shared secret for local JWT fast-path verification. If unset, validate via /auth/whoami.
    jwt_secret: str | None = None
    admin_groups: list[str] = ["admin"]

    # --- Reserved groups ---
    reserved_groups: list[str] = DEFAULT_RESERVED_GROUPS

    # --- Scheduler (used from US5 onward) ---
    expiry_sweep_seconds: int = 300
    reconcile_seconds: int = 1800
    expiry_warning_days: int = 30

    # --- Misc ---
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:5174", "http://localhost:80"]

    def is_reserved(self, name: str) -> bool:
        lowered = name.strip().lower()
        reserved = {g.lower() for g in self.reserved_groups} | {g.lower() for g in self.admin_groups}
        return lowered in reserved or lowered == ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
