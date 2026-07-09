"""Audit log query API (T048).

The audit *writing* is foundational (T009); this exposes the filterable *view* (US7).
Restricted to admins — the log spans every actor and entity.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from ..auth.deps import get_ctx, require_admin
from ..auth.jwt import CurrentUser
from ..context import AppContext
from ..models.audit import AuditEntry

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=list[AuditEntry])
async def list_audit(
    actor: str | None = None,
    entityType: str | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(require_admin),
):
    return await ctx.audit.query(
        actor=actor,
        entity_type=entityType,
        date_from=from_,
        date_to=to,
        skip=skip,
        limit=limit,
    )
