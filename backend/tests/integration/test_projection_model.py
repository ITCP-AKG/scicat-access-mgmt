"""Projection model regressions (Phase 3): SciCat's login wipe is repaired by the login
watcher and by /me, deleted/retired groups leave identities, foreign strings survive,
existing holders need an explicit decision, and writes are compare-and-set."""

from datetime import datetime, timedelta, timezone

import pytest

from app.scheduler.jobs import SchedulerJobs
from app.services.projection import ProjectionService
from app.services.reconcile import ReconcileService

pytestmark = pytest.mark.asyncio


async def _groups(ctx, user_id):
    doc = await ctx.scicat_db["UserIdentity"].find_one({"userId": user_id})
    return doc["profile"].get("accessGroups")


async def _scicat_login(ctx, user_id, static=("",), at=None):
    """What SciCat's login strategies do: replace accessGroups and bump `modified`."""
    await ctx.scicat_db["UserIdentity"].update_one(
        {"userId": user_id},
        {"$set": {"profile.accessGroups": list(static), "modified": at or ctx.now()}},
    )


async def _team_with_alice(client, admin_headers, name="team"):
    await client.post(
        "/api/v1/groups", headers=admin_headers, json={"name": name, "category": "research-group"}
    )
    resp = await client.post(
        f"/api/v1/groups/{name}/members", headers=admin_headers, json={"userId": "user-id"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_login_watcher_restores_wiped_groups(client, admin_headers, ctx):
    await _team_with_alice(client, admin_headers)
    await _scicat_login(ctx, "user-id")
    assert await _groups(ctx, "user-id") == [""]

    jobs = SchedulerJobs(ctx)
    first = await jobs.login_watch()
    assert first["usersUpdated"] == 1
    assert set(await _groups(ctx, "user-id")) == {"", "team"}

    # our own write does not bump `modified`, so the next tick has nothing to fix
    doc = await ctx.scicat_db["UserIdentity"].find_one({"userId": "user-id"})
    assert doc["modified"] == ctx.now()
    second = await jobs.login_watch()
    assert second["usersUpdated"] == 0


async def test_login_watcher_cursor_skips_old_identities(client, admin_headers, ctx, clock):
    await _team_with_alice(client, admin_headers)
    jobs = SchedulerJobs(ctx)
    await _scicat_login(ctx, "user-id")
    await jobs.login_watch()

    clock.set(ctx.now() + timedelta(hours=1))
    await _scicat_login(ctx, "bob-id", static=("x",))
    result = await jobs.login_watch()
    assert result["usersChecked"] == 1  # alice's older change is behind cursor - overlap


async def test_me_reprojects_and_returns_fresh_groups(client, admin_headers, user_headers, ctx):
    await _team_with_alice(client, admin_headers)
    before = await client.get("/api/v1/me", headers=user_headers)
    assert "team" in before.json()["currentGroups"]

    await _scicat_login(ctx, "user-id")  # login wipes the projected group
    resp = await client.get("/api/v1/me", headers=user_headers)
    assert resp.status_code == 200
    assert "team" in resp.json()["currentGroups"]
    assert "team" in await _groups(ctx, "user-id")


async def test_cascade_delete_removes_group_from_identities(client, admin_headers, ctx):
    await _team_with_alice(client, admin_headers)
    resp = await client.delete("/api/v1/groups/team?cascade=true", headers=admin_headers)
    assert resp.status_code == 204
    groups = await _groups(ctx, "user-id")
    assert "team" not in groups and "u.alice" in groups


async def test_retire_and_unretire(client, admin_headers, ctx):
    await _team_with_alice(client, admin_headers)
    await client.patch("/api/v1/groups/team", headers=admin_headers, json={"status": "retired"})
    assert "team" not in await _groups(ctx, "user-id")
    await client.patch("/api/v1/groups/team", headers=admin_headers, json={"status": "active"})
    assert "team" in await _groups(ctx, "user-id")


async def test_name_of_vanished_group_still_removed_via_last_projected(
    client, admin_headers, ctx
):
    await _team_with_alice(client, admin_headers)
    # simulate a group that disappeared without cleanup (e.g. pre-fix deletion)
    await ctx.app_db.groups.delete_one({"name": "team"})
    result = await ReconcileService(ctx).reconcile()
    assert result.usersUpdated == 1
    assert "team" not in await _groups(ctx, "user-id")


async def test_foreign_strings_are_preserved(client, admin_headers, ctx):
    await ctx.scicat_db["UserIdentity"].update_one(
        {"userId": "user-id"}, {"$push": {"profile.accessGroups": "AKG"}}
    )
    await _team_with_alice(client, admin_headers)
    groups = await _groups(ctx, "user-id")
    assert {"AKG", "team", "u.alice", "globalaccess"} <= set(groups)


async def test_reconcile_strips_registered_name_from_non_members(client, admin_headers, ctx):
    await client.post(
        "/api/v1/groups", headers=admin_headers, json={"name": "team", "category": "other"}
    )
    # someone hand-edits bob's identity in Mongo
    await ctx.scicat_db["UserIdentity"].update_one(
        {"userId": "bob-id"}, {"$push": {"profile.accessGroups": "team"}}
    )
    result = await ReconcileService(ctx).reconcile()
    assert [d.userId for d in result.drift] == ["bob-id"]
    assert "team" not in await _groups(ctx, "bob-id")


async def test_create_with_existing_holders_requires_decision(client, admin_headers, ctx):
    await ctx.scicat_db["UserIdentity"].update_one(
        {"userId": "bob-id"}, {"$push": {"profile.accessGroups": "AKG"}}
    )
    check = await client.get(
        "/api/v1/groups/-/name-check", headers=admin_headers, params={"name": "AKG"}
    )
    assert check.json()["holders"] == 1

    body = {"name": "AKG", "category": "research-group"}
    undecided = await client.post("/api/v1/groups", headers=admin_headers, json=body)
    assert undecided.status_code == 409
    assert "AKG" in await _groups(ctx, "bob-id")

    adopted = await client.post(
        "/api/v1/groups", headers=admin_headers, json={**body, "importHolders": True}
    )
    assert adopted.status_code == 201
    members = (await client.get("/api/v1/groups/AKG/members", headers=admin_headers)).json()
    assert [m["userId"] for m in members] == ["bob-id"]
    assert "AKG" in await _groups(ctx, "bob-id")


async def test_create_with_holders_dropped(client, admin_headers, ctx):
    await ctx.scicat_db["UserIdentity"].update_one(
        {"userId": "bob-id"}, {"$push": {"profile.accessGroups": "AKG"}}
    )
    resp = await client.post(
        "/api/v1/groups",
        headers=admin_headers,
        json={"name": "AKG", "category": "other", "importHolders": False},
    )
    assert resp.status_code == 201
    assert "AKG" not in await _groups(ctx, "bob-id")


async def test_write_is_compare_and_set(client, admin_headers, ctx):
    """A SciCat login landing between our read and write must not be clobbered."""
    await client.post(
        "/api/v1/groups", headers=admin_headers, json={"name": "team", "category": "other"}
    )
    from app.models.membership import Membership

    await ctx.app_db.memberships.insert_one(
        Membership(groupName="team", userId="user-id", status="active").model_dump()
    )
    svc = ProjectionService(ctx)
    original_plan = svc.plan_user
    calls = 0

    async def plan_then_login(user_id, registry=None):
        nonlocal calls
        plan = await original_plan(user_id, registry)
        calls += 1
        if calls == 1:  # SciCat login commits right after our read
            await _scicat_login(ctx, "user-id", static=("fresh-static",))
        return plan

    svc.plan_user = plan_then_login
    changed, _ = await svc.project_user("user-id")
    assert changed and calls == 2
    assert set(await _groups(ctx, "user-id")) == {"fresh-static", "team"}


async def test_identity_without_access_groups_field(client, admin_headers, ctx):
    await ctx.scicat_db["UserIdentity"].update_one(
        {"userId": "bob-id"}, {"$unset": {"profile.accessGroups": ""}}
    )
    await client.post(
        "/api/v1/groups", headers=admin_headers, json={"name": "team", "category": "other"}
    )
    resp = await client.post(
        "/api/v1/groups/team/members", headers=admin_headers, json={"userId": "bob-id"}
    )
    assert resp.status_code == 201
    assert await _groups(ctx, "bob-id") == ["team"]


async def test_watcher_first_run_without_cursor(client, admin_headers, ctx):
    await _team_with_alice(client, admin_headers)
    await _scicat_login(ctx, "user-id", at=datetime(2025, 1, 1, tzinfo=timezone.utc))
    # an ancient change is outside the first-run lookback: left to reconcile
    result = await SchedulerJobs(ctx).login_watch()
    assert result["usersChecked"] == 0
    await ReconcileService(ctx).reconcile()
    assert "team" in await _groups(ctx, "user-id")


async def test_watcher_retries_failed_user(client, admin_headers, ctx, clock, monkeypatch):
    await _team_with_alice(client, admin_headers)
    t0 = ctx.now()
    await _scicat_login(ctx, "user-id", at=t0)

    original = ProjectionService.project_user
    failing = {"user-id"}

    async def flaky(self, user_id, **kw):
        if user_id in failing:
            raise RuntimeError("transient")
        return await original(self, user_id, **kw)

    monkeypatch.setattr(ProjectionService, "project_user", flaky)
    jobs = SchedulerJobs(ctx)
    first = await jobs.login_watch()
    assert first["errors"] and "team" not in await _groups(ctx, "user-id")

    # a much later login of someone else must not push alice's change out of the window
    clock.set(t0 + timedelta(minutes=10))
    await _scicat_login(ctx, "bob-id", static=("x",), at=ctx.now())
    failing.clear()
    second = await jobs.login_watch()
    assert second["usersChecked"] == 2
    assert "team" in await _groups(ctx, "user-id")

    # once applied, alice is not re-planned on later ticks
    third = await jobs.login_watch()
    assert third["usersChecked"] == 0
