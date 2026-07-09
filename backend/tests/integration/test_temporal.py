"""US5 temporal access: expiry sweep (expire lapsed, activate reached) + re-projection,
and the /expiry dashboard (T037, quickstart V5, SC-003). Uses the injected clock."""

from datetime import datetime, timezone

import pytest

from app.scheduler.jobs import SchedulerJobs

pytestmark = pytest.mark.asyncio


def _dt(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=timezone.utc)


async def _identity_groups(ctx, user_id):
    doc = await ctx.scicat_db["UserIdentity"].find_one({"userId": user_id})
    return doc["profile"]["accessGroups"]


async def _make_group(client, headers, name="team"):
    await client.post(
        "/api/v1/groups", headers=headers, json={"name": name, "category": "research-group"}
    )


async def test_sweep_expires_lapsed_membership_and_reprojects(client, admin_headers, ctx, clock):
    clock.set(_dt(1))
    await _make_group(client, admin_headers)
    await client.post(
        "/api/v1/groups/team/members",
        headers=admin_headers,
        json={"userId": "user-id", "expiresAt": _dt(5).isoformat()},
    )
    assert "team" in await _identity_groups(ctx, "user-id")

    # advance past expiry and sweep
    clock.set(_dt(10))
    result = await SchedulerJobs(ctx).expiry_sweep()
    assert result["membershipsExpired"] == 1

    assert "team" not in await _identity_groups(ctx, "user-id")
    # intrinsic strings preserved
    assert "u.alice" in await _identity_groups(ctx, "user-id")
    doc = await ctx.app_db.memberships.find_one({"userId": "user-id"})
    assert doc["status"] == "expired"


async def test_sweep_activates_scheduled_membership_and_projects(client, admin_headers, ctx, clock):
    clock.set(_dt(1))
    await _make_group(client, admin_headers)
    await client.post(
        "/api/v1/groups/team/members",
        headers=admin_headers,
        json={"userId": "bob-id", "effectiveFrom": _dt(5).isoformat()},
    )
    # scheduled => not yet projected
    assert "team" not in await _identity_groups(ctx, "bob-id")
    doc = await ctx.app_db.memberships.find_one({"userId": "bob-id"})
    assert doc["status"] == "scheduled"

    clock.set(_dt(6))
    result = await SchedulerJobs(ctx).expiry_sweep()
    assert result["membershipsActivated"] == 1
    assert "team" in await _identity_groups(ctx, "bob-id")


async def test_sweep_is_idempotent(client, admin_headers, ctx, clock):
    clock.set(_dt(1))
    await _make_group(client, admin_headers)
    await client.post(
        "/api/v1/groups/team/members",
        headers=admin_headers,
        json={"userId": "user-id", "expiresAt": _dt(5).isoformat()},
    )
    clock.set(_dt(10))
    first = await SchedulerJobs(ctx).expiry_sweep()
    second = await SchedulerJobs(ctx).expiry_sweep()
    assert first["membershipsExpired"] == 1
    assert second["membershipsExpired"] == 0


async def test_sweep_expires_grant_and_withdraws(client, admin_headers, ctx, clock):
    clock.set(_dt(1))
    await _make_group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig", accessGroups=[])
    await client.post(
        "/api/v1/grants",
        headers=admin_headers,
        json={
            "groupName": "team",
            "resourceType": "dataset",
            "resourceIds": ["ds-1"],
            "mode": "access",
            "expiresAt": _dt(5).isoformat(),
        },
    )
    assert "team" in ctx.scicat.resources[("dataset", "ds-1")]["accessGroups"]

    clock.set(_dt(10))
    result = await SchedulerJobs(ctx).expiry_sweep()
    assert result["grantsExpired"] == 1
    assert "team" not in ctx.scicat.resources[("dataset", "ds-1")]["accessGroups"]


async def test_expiry_dashboard_lists_soon_recent_and_grants(client, admin_headers, ctx, clock):
    clock.set(_dt(10))
    await _make_group(client, admin_headers)
    # expiring-soon membership (active, expiry within window)
    await client.post(
        "/api/v1/groups/team/members",
        headers=admin_headers,
        json={"userId": "user-id", "expiresAt": _dt(20).isoformat()},
    )
    # recently-expired membership for bob (expire it via the sweep)
    await client.post(
        "/api/v1/groups/team/members",
        headers=admin_headers,
        json={"userId": "bob-id", "expiresAt": _dt(12).isoformat()},
    )
    # expiring grant
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig", accessGroups=[])
    await client.post(
        "/api/v1/grants",
        headers=admin_headers,
        json={
            "groupName": "team",
            "resourceType": "dataset",
            "resourceIds": ["ds-1"],
            "mode": "access",
            "expiresAt": _dt(20).isoformat(),
        },
    )

    clock.set(_dt(15))
    await SchedulerJobs(ctx).expiry_sweep()

    resp = await client.get("/api/v1/expiry?withinDays=30", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert [m["userId"] for m in body["expiringSoon"]] == ["user-id"]
    assert [m["userId"] for m in body["recentlyExpired"]] == ["bob-id"]
    assert [g["resourceId"] for g in body["expiringGrants"]] == ["ds-1"]
