"""catorga project API: keep a project's sharing in step with its records."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth.deps import current_user, get_ctx
from ..auth.jwt import CurrentUser
from ..context import AppContext
from ..services.grants import GrantService
from ..services.scicat_client import ScicatError, ScicatUnavailable

router = APIRouter(tags=["projects"])


@router.post("/projects/{proposal_id}/sync")
async def sync_project(
    proposal_id: str,
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(current_user),
):
    """Extend the project's active grants to its records that lack them (catorga calls
    this right after creating a sample or dataset; the scheduler does it periodically).
    Idempotent, and it only applies grants that already exist, so any signed-in user may
    trigger it."""
    try:
        added = await GrantService(ctx).cascade_project(proposal_id, actor="system")
    except ScicatUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"SciCat unavailable: {exc}") from exc
    except ScicatError as exc:
        raise HTTPException(status_code=502, detail=f"SciCat error: {exc}") from exc
    return {"recordsAdded": added}
