"""Small shared helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Canonical 'now' in UTC. Override via dependency injection in tests."""
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex
