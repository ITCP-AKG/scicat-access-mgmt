"""Transfer rules + records API (T045)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.deps import get_ctx, require_admin
from ..auth.jwt import CurrentUser
from ..context import AppContext
from ..models.transfer import (
    Departure,
    TransferBatchResult,
    TransferRecord,
    TransferRule,
    TransferRuleCreate,
)
from ..services.transfers import (
    InvalidTransferRuleError,
    TransferBatchNotFoundError,
    TransferRuleNotFoundError,
    TransferService,
)

router = APIRouter(tags=["transfers"])


def _service(ctx: AppContext) -> TransferService:
    return TransferService(ctx)


@router.get("/transfer-rules", response_model=list[TransferRule])
async def list_rules(
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(require_admin),
):
    return await _service(ctx).list_rules()


@router.post("/transfer-rules", response_model=TransferRule, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: TransferRuleCreate,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(require_admin),
):
    try:
        return await _service(ctx).create_rule(payload, actor=user.userId)
    except InvalidTransferRuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    except InvalidTransferRuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    batchId: str | None = None,
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(require_admin),
):
    return await _service(ctx).list_records(fromUserId, outcome, batchId)


@router.get("/transfer-batches", response_model=list[Departure])
async def list_batches(
    userId: str | None = None,
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(require_admin),
):
    """Departures (one per deactivation or lapse); each is the batch of its records."""
    return await _service(ctx).list_departures(userId)


@router.post("/transfer-batches/{batch_id}/retry", response_model=TransferBatchResult)
async def retry_batch(
    batch_id: str,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(require_admin),
):
    """Re-run a departure with the current rules: failed and pending resources are retried
    (e.g. after adding a rule), completed transfers are left alone."""
    try:
        return await _service(ctx).retry_batch(batch_id, actor=user.userId)
    except TransferBatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="transfer batch not found") from exc
