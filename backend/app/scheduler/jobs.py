"""Background scheduler: expiry sweep, login watcher, project cascade and periodic
reconcile (T039).

The sweep materialises membership/grant temporal transitions and re-projects; the login
watcher re-projects users whose SciCat identity was just rewritten by a login (SciCat
replaces profile.accessGroups on every login); the reconcile job repairs any remaining
drift between app state and SciCat; the project cascade extends project grants to records
added to a project and retries partly refused project moves. All run under a Mongo lease
(`sync_state._id == 'scheduler-lease'`) so only one app instance acts at a time (R6), and
all are attributed to the `system` actor in the audit log.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ..context import AppContext
from ..services.grants import GrantService
from ..services.memberships import MembershipService
from ..services.projection import ProjectionService, SyncResult, identity_user_id
from ..services.projects import ProjectService
from ..services.reconcile import ReconcileService
from ..services.transfers import TransferService
from ..util import new_id

logger = logging.getLogger(__name__)

LEASE_ID = "scheduler-lease"
LOGIN_WATCH_ID = "login-watch"
# Re-scan this far behind the cursor so identity writes that commit out of timestamp order
# are not missed (re-projecting is idempotent and cheap).
LOGIN_WATCH_OVERLAP = timedelta(seconds=60)
# Without a cursor (first start), look back this far; older logins are left to reconcile.
LOGIN_WATCH_INITIAL_LOOKBACK = timedelta(days=1)
# A change that keeps failing holds the cursor back at most this long (then reconcile).
LOGIN_WATCH_MAX_RETRY = timedelta(hours=1)


class SchedulerJobs:
    """The job bodies, independent of APScheduler so tests can call them directly."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    async def expiry_sweep(self, actor: str = "system") -> dict[str, Any]:
        ran_at = self.ctx.now()
        membership_result = await MembershipService(self.ctx).sweep(actor)
        grant_result = await GrantService(self.ctx).sweep(actor)
        transfers_run = await self._expiry_transfers(
            membership_result.pop("expiredGroupsByUser", {}), actor
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

    async def _expiry_transfers(self, expired: dict[str, list[str]], actor: str) -> int:
        """Run ownership transfer for users whose access fully lapsed (no remaining
        active/scheduled memberships and no managed group), matching rules against the
        groups that lapsed.
        Runs once per lapse: the memberships are expired now, so later sweeps skip them."""
        transfer_svc = TransferService(self.ctx)
        records = 0
        for user_id, groups in sorted(expired.items()):
            remaining = await self.ctx.app_db.memberships.count_documents(
                {"userId": user_id, "status": {"$in": ["active", "scheduled"]}}
            )
            # managers keep member access to the groups they manage
            if remaining or await self.ctx.app_db.groups.count_documents({"managers": user_id}):
                continue
            try:
                batch = await transfer_svc.transfer_for_user(
                    user_id, reason="expiry", actor=actor, groups=groups
                )
            except Exception:  # noqa: BLE001 - one user must not block the others
                logger.exception("expiry transfer failed for %s", user_id)
                continue
            records += len(batch.records)
        return records

    async def project_cascade(self, actor: str = "system") -> dict[str, Any]:
        result = await GrantService(self.ctx).cascade_all(actor)
        result["movesRetried"] = await ProjectService(self.ctx).retry_incomplete()
        return result

    async def reconcile(self, actor: str = "system"):
        result = await ReconcileService(self.ctx).reconcile(actor=actor)
        try:
            await TransferService(self.ctx).retry_incomplete(actor=actor)
        except Exception:  # noqa: BLE001 - next cycle retries again
            logger.exception("retrying incomplete transfer batches failed")
        return result

    async def login_watch(self, actor: str = "system") -> dict[str, Any]:
        """Re-project users whose SciCat identity changed since the last run.

        SciCat bumps UserIdentity.modified when a login rewrites profile.accessGroups; the
        app's own projection writes leave it untouched, so this does not feed on itself.
        Changes inside the overlap window that were already handled (same user, same
        `modified`) are skipped; failures are retried on the next tick.
        """
        state = await self.ctx.app_db.sync_state.find_one({"_id": LOGIN_WATCH_ID}) or {}
        cursor = state.get("cursor") or self.ctx.now() - LOGIN_WATCH_INITIAL_LOOKBACK
        handled_before = set(state.get("handled") or [])

        changes: dict[str, datetime] = {}  # user -> latest `modified` seen
        async for doc in self.ctx.scicat_db[self.ctx.settings.scicat_identity_collection].find(
            {"modified": {"$gt": cursor - LOGIN_WATCH_OVERLAP}},
            {"userId": 1, "profile.id": 1, "modified": 1},
        ):
            modified = doc.get("modified")
            if not isinstance(modified, datetime):
                continue
            uid = identity_user_id(doc)
            if uid not in changes or modified > changes[uid]:
                changes[uid] = modified

        def key(uid: str) -> str:
            return f"{uid}|{changes[uid].isoformat()}"

        projection = ProjectionService(self.ctx)
        registry = await projection.registry()
        result = SyncResult(ranAt=self.ctx.now())
        handled: set[str] = set()
        failed: list[datetime] = []
        checked = 0
        for uid in sorted(changes):
            if key(uid) in handled_before:
                handled.add(key(uid))
                continue
            checked += 1
            try:
                res = await projection.project_user(uid, actor=actor, registry=registry)
                if res and res[0]:
                    result.usersUpdated += 1
                handled.add(key(uid))
            except Exception as exc:  # noqa: BLE001 - retried next tick
                result.errors.append(f"{uid}: {exc}")
                failed.append(changes[uid])

        newest = max([cursor, *changes.values()])
        # never move past a change that could not be applied (bounded by MAX_RETRY)
        new_cursor = max(min([newest, *failed]), newest - LOGIN_WATCH_MAX_RETRY)
        handled = {k for k in handled if datetime.fromisoformat(k.rsplit("|", 1)[1])
                   > new_cursor - LOGIN_WATCH_OVERLAP}
        await self.ctx.app_db.sync_state.update_one(
            {"_id": LOGIN_WATCH_ID},
            {"$set": {"cursor": new_cursor, "handled": sorted(handled),
                      "lastRunAt": self.ctx.now(),
                      "lastResult": result.model_dump(mode="json")}},
            upsert=True,
        )
        return {"usersChecked": checked, **result.model_dump()}


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
            # also once at startup: catches logins/changes made while the app was down
            next_run_time=datetime.now(timezone.utc),
        )
        self._sched.add_job(
            self._guarded, "interval", args=[self.jobs.login_watch],
            seconds=self.ctx.settings.login_watch_seconds, id="login-watch",
        )
        self._sched.add_job(
            self._guarded, "interval", args=[self.jobs.project_cascade],
            seconds=self.ctx.settings.project_cascade_seconds, id="project-cascade",
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
