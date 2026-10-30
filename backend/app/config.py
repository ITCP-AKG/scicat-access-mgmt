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
    scicat_timeout_seconds: float = 10.0
    # Functional account used for ALL SciCat resource reads/writes (the app enforces its own
    # authorization). Either username/password (logged in lazily, re-login on expiry) or a
    # pre-issued token.
    scicat_service_username: str | None = None
    scicat_service_password: str | None = None
    scicat_service_token: str | None = None

    # --- Auth ---
    # Optional shared secret for a local signature pre-check. Validity is always confirmed
    # via SciCat /auth/whoami (cached briefly per token).
    jwt_secret: str | None = None
    whoami_cache_seconds: float = 60.0
    admin_groups: list[str] = ["admin"]

    # --- Ownership transfer ---
    # Template of a user's legacy personal ownerGroup, e.g. "{username}" (older catorga
    # records). Only used to recognise such resources on departure so a group successor
    # can take them over; it is not projected (SciCat never treats a username as a group).
    personal_group_template: str = ""

    # --- Invitations ---
    # The invitation link is this base + the token, e.g. "https://host/#/invite/" (catorga's
    # invite page). Empty: the API returns only the token.
    invite_link_base: str = ""
    invite_default_days: int = 14
    invite_max_days: int = 90

    # --- Reserved groups ---
    reserved_groups: list[str] = DEFAULT_RESERVED_GROUPS

    # --- Scheduler (used from US5 onward) ---
    expiry_sweep_seconds: int = 300
    reconcile_seconds: int = 1800
    # SciCat rewrites profile.accessGroups on every login; re-project changed identities.
    login_watch_seconds: int = 15
    expiry_warning_days: int = 30
    # Extend project grants to records added to a project since (also done on demand by
    # POST /projects/{id}/sync), and retry partly refused project moves.
    project_cascade_seconds: int = 300

    # --- Misc ---
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:5174", "http://localhost:80"]

    def is_reserved(self, name: str) -> bool:
        lowered = name.strip().lower()
        reserved = {g.lower() for g in self.reserved_groups} | {g.lower() for g in self.admin_groups}
        return lowered in reserved or lowered == ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
