"""Transfer rules + records API (T045)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.deps import current_user, get_ctx, require_admin
from ..auth.jwt import CurrentUser
from ..context import AppContext
from ..models.transfer import TransferRecord, TransferRule, TransferRuleCreate
from ..services.transfers import TransferRuleNotFoundError, TransferService

router = APIRouter(tags=["transfers"])


def _service(ctx: AppContext) -> TransferService:
    return TransferService(ctx)


@router.get("/transfer-rules", response_model=list[TransferRule])
async def list_rules(
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(current_user),
):
    return await _service(ctx).list_rules()


@router.post("/transfer-rules", response_model=TransferRule, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: TransferRuleCreate,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(require_admin),
):
    return await _service(ctx).create_rule(payload, actor=user.userId)


@router.patch("/transfer-rules/{rule_id}", response_model=TransferRule)
async def update_rule(
    rule_id: str,
    payload: TransferRuleCreate,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(require_admin),
):
    try:
        return await _service(ctx).update_rule(rule_id, payload, actor=user.userId)
    except TransferRuleNotFoundError as exc:
        raise HTTPException(status_code=404, detail="transfer rule not found") from exc


@router.delete("/transfer-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: str,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(require_admin),
):
    try:
        await _service(ctx).delete_rule(rule_id, actor=user.userId)
    except TransferRuleNotFoundError as exc:
        raise HTTPException(status_code=404, detail="transfer rule not found") from exc


@router.get("/transfer-records", response_model=list[TransferRecord])
async def list_records(
    fromUserId: str | None = None,
    outcome: str | None = None,
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(current_user),
):
    return await _service(ctx).list_records(fromUserId, outcome)
