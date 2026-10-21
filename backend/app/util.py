"""Small shared helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Canonical 'now' in UTC. Override via dependency injection in tests."""
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


def window_error(
    effective_from: datetime | None, expires_at: datetime | None, now: datetime
) -> str | None:
    """Why an (effectiveFrom, expiresAt) window is invalid, or None if it is fine."""
    for label, value in (("effectiveFrom", effective_from), ("expiresAt", expires_at)):
        if value is not None and value.tzinfo is None:
            return f"{label} must include a timezone (UTC)"
    if expires_at is not None and expires_at <= now:
        return "expiresAt must be in the future"
    if effective_from is not None and expires_at is not None and effective_from >= expires_at:
        return "effectiveFrom must be before expiresAt"
    return None
