"""Background scheduler: expiry sweep + periodic reconcile (T039).

The sweep materialises membership/grant temporal transitions and re-projects; the
reconcile job repairs drift between app state and SciCat. Both run under a Mongo lease
(`sync_state._id == 'scheduler-lease'`) so only one app instance acts at a time (R6), and
both are attributed to the `system` actor in the audit log.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from ..context import AppContext
from ..services.grants import GrantService
from ..services.memberships import MembershipService
from ..services.reconcile import ReconcileService
from ..services.transfers import TransferService
from ..util import new_id

logger = logging.getLogger(__name__)

LEASE_ID = "scheduler-lease"


class SchedulerJobs:
    """The job bodies, independent of APScheduler so tests can call them directly."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    async def expiry_sweep(self, actor: str = "system") -> dict[str, Any]:
        ran_at = self.ctx.now()
        membership_result = await MembershipService(self.ctx).sweep(actor)
        grant_result = await GrantService(self.ctx).sweep(actor)
        transfers_run = await self._expiry_transfers(
            membership_result.pop("expiredUserIds", []), actor
        )
        result: dict[str, Any] = {
            "ranAt": ran_at,
            **membership_result,
            **grant_result,
            "transferRecords": transfers_run,
        }
        await self.ctx.app_db.sync_state.update_one(
            {"_id": "expiry-sweep"},
            {"$set": {"lastRunAt": ran_at, "lastResult": {
                k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in result.items()
            }}},
            upsert=True,
        )
        return result

    async def _expiry_transfers(self, expired_user_ids: list[str], actor: str) -> int:
        """Run ownership transfer for users whose access fully lapsed (no remaining
        active/scheduled memberships). Idempotent via the transfer batch guard."""
        transfer_svc = TransferService(self.ctx)
        records = 0
        for user_id in expired_user_ids:
            remaining = await self.ctx.app_db.memberships.count_documents(
                {"userId": user_id, "status": {"$in": ["active", "scheduled"]}}
            )
            if remaining:
                continue
            batch = await transfer_svc.transfer_for_user(user_id, reason="expiry", actor=actor)
            records += len(batch.records)
        return records

    async def reconcile(self, actor: str = "system"):
        return await ReconcileService(self.ctx).reconcile(actor=actor)


async def acquire_lease(ctx: AppContext, owner: str, ttl_seconds: int = 600) -> bool:
    """Best-effort single-leader lock. True if this owner now holds the lease."""
    now = ctx.now()
    expires = now + timedelta(seconds=ttl_seconds)
    col = ctx.app_db.sync_state
    # Claim if the lease is free/expired or already ours.
    res = await col.update_one(
        {"_id": LEASE_ID, "$or": [{"leaseExpiresAt": {"$lte": now}}, {"leaseOwner": owner}]},
        {"$set": {"leaseOwner": owner, "leaseExpiresAt": expires}},
    )
    if res.matched_count:
        return True
    # No lease document yet — create it atomically.
    await col.update_one(
        {"_id": LEASE_ID},
        {"$setOnInsert": {"leaseOwner": owner, "leaseExpiresAt": expires}},
        upsert=True,
    )
    doc = await col.find_one({"_id": LEASE_ID})
    return bool(doc and doc.get("leaseOwner") == owner)


class Scheduler:
    """APScheduler wrapper started/stopped from the FastAPI lifespan."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.jobs = SchedulerJobs(ctx)
        self._owner = new_id()
        self._sched = None

    def start(self) -> None:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        self._sched = AsyncIOScheduler(timezone="UTC")
        self._sched.add_job(
            self._guarded, "interval", args=[self.jobs.expiry_sweep],
            seconds=self.ctx.settings.expiry_sweep_seconds, id="expiry-sweep",
        )
        self._sched.add_job(
            self._guarded, "interval", args=[self.jobs.reconcile],
            seconds=self.ctx.settings.reconcile_seconds, id="reconcile",
        )
        self._sched.start()
        logger.info("scheduler started (owner=%s)", self._owner)

    async def _guarded(self, job) -> None:
        try:
            if await acquire_lease(self.ctx, self._owner):
                await job()
        except Exception:  # noqa: BLE001 - never let a tick crash the scheduler
            logger.exception("scheduler job %s failed", getattr(job, "__name__", job))

    def stop(self) -> None:
        if self._sched is not None:
            self._sched.shutdown(wait=False)
            self._sched = None
