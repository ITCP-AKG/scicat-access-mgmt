"""Grant semantics regressions (Phase 4): grants only undo what they did, owner restore is
guarded, withdrawal failures are retried instead of swallowed, scheduled grants that never
applied never withdraw anything, and reconcile detects grant drift."""

from datetime import datetime, timezone

import pytest

from app.models.resource_grant import ResourceGrant
from app.scheduler.jobs import SchedulerJobs
from app.services.reconcile import ReconcileService

pytestmark = pytest.mark.asyncio


def _dt(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=timezone.utc)


async def _group(client, headers, name="team", **extra):
    resp = await client.post(
        "/api/v1/groups", headers=headers, json={"name": name, "category": "other", **extra}
    )
    assert resp.status_code == 201, resp.text


async def _apply(client, headers, rid="ds-1", mode="access", group="team", **window):
    body = {"groupName": group, "resourceType": "dataset", "resourceIds": [rid], "mode": mode}
    body.update({k: v.isoformat() for k, v in window.items()})
    resp = await client.post("/api/v1/grants", headers=headers, json=body)
    assert resp.status_code == 207, resp.text
    return resp.json()["items"][0]


def _res(ctx, rid="ds-1"):
    return ctx.scicat.resources[("dataset", rid)]


async def _grant(ctx, grant_id) -> dict:
    return await ctx.app_db.resource_grants.find_one({"id": grant_id}, {"_id": 0})


async def test_preexisting_access_entry_survives_removal(client, admin_headers, ctx):
    await _group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig", accessGroups=["team"])
    item = await _apply(client, admin_headers)
    assert ctx.scicat.patches == []  # nothing to change
    await client.delete(f"/api/v1/grants/{item['grantId']}", headers=admin_headers)
    assert _res(ctx)["accessGroups"] == ["team"]


async def test_owner_grant_on_already_owned_resource_is_left_alone(client, admin_headers, ctx):
    await _group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="team")
    item = await _apply(client, admin_headers, mode="owner")
    await client.delete(f"/api/v1/grants/{item['grantId']}", headers=admin_headers)
    assert _res(ctx)["ownerGroup"] == "team"
    assert ctx.scicat.patches == []


async def test_reapplying_owner_grant_keeps_original_owner(client, admin_headers, ctx, clock):
    clock.set(_dt(1))
    await _group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig")
    first = await _apply(client, admin_headers, mode="owner")
    second = await _apply(client, admin_headers, mode="owner", expiresAt=_dt(20))

    old = await _grant(ctx, first["grantId"])
    new = await _grant(ctx, second["grantId"])
    assert old["status"] == "removed" and old["supersededBy"] == new["id"]
    assert new["previousOwnerGroup"] == "orig"

    await client.delete(f"/api/v1/grants/{second['grantId']}", headers=admin_headers)
    assert _res(ctx)["ownerGroup"] == "orig"


async def test_second_owner_grant_for_other_group_conflicts(client, admin_headers, ctx):
    await _group(client, admin_headers)
    await _group(client, admin_headers, "other")
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig")
    await _apply(client, admin_headers, mode="owner")
    item = await _apply(client, admin_headers, mode="owner", group="other")
    assert item["ok"] is False and "remove it first" in item["error"]
    assert _res(ctx)["ownerGroup"] == "team"


async def test_failed_withdrawal_is_kept_pending_and_retried(client, admin_headers, ctx):
    await _group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig", accessGroups=[])
    item = await _apply(client, admin_headers)

    ctx.scicat.fail_patch_ids.add("ds-1")
    resp = await client.delete(f"/api/v1/grants/{item['grantId']}", headers=admin_headers)
    assert resp.status_code == 202
    body = resp.json()
    assert body["pendingRemoval"] is True and body["status"] == "active" and body["lastError"]
    assert "team" in _res(ctx)["accessGroups"]  # still effective, and the app says so

    # still failing: the sweep keeps it pending (no audit spam)
    result = await SchedulerJobs(ctx).expiry_sweep()
    assert result["grantsPendingRemoval"] == 1

    ctx.scicat.fail_patch_ids.clear()
    result = await SchedulerJobs(ctx).expiry_sweep()
    assert result["grantsRetried"] == 1
    grant = await _grant(ctx, item["grantId"])
    assert grant["status"] == "removed" and grant["pendingRemoval"] is False
    assert grant["endedBy"] == "admin-id"
    assert "team" not in _res(ctx)["accessGroups"]
    failures = await ctx.app_db.audit_log.count_documents({"action": "grant.withdraw_failed"})
    assert failures == 1


async def test_owner_changed_elsewhere_is_not_restored(client, admin_headers, ctx):
    await _group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig")
    item = await _apply(client, admin_headers, mode="owner")
    _res(ctx)["ownerGroup"] = "new-owner"  # changed directly in SciCat
    resp = await client.delete(f"/api/v1/grants/{item['grantId']}", headers=admin_headers)
    assert resp.status_code == 204
    assert _res(ctx)["ownerGroup"] == "new-owner"
    assert "already changed" in (await _grant(ctx, item["grantId"]))["lastError"]


async def test_never_patches_empty_owner_group(client, admin_headers, ctx):
    """Legacy grants without a recorded previous owner leave ownership in place."""
    await _group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="team")
    legacy = ResourceGrant(
        groupName="team", resourceType="dataset", resourceId="ds-1", mode="owner",
        status="active", previousOwnerGroup=None,
    )
    await ctx.app_db.resource_grants.insert_one(legacy.model_dump())
    resp = await client.delete(f"/api/v1/grants/{legacy.id}", headers=admin_headers)
    assert resp.status_code == 204
    assert _res(ctx)["ownerGroup"] == "team"
    assert all(p[2].get("ownerGroup") != "" for p in ctx.scicat.patches)


async def test_scheduled_grant_that_lapsed_unapplied_withdraws_nothing(
    client, admin_headers, ctx, clock
):
    clock.set(_dt(1))
    await _group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig", accessGroups=["team"])
    item = await _apply(client, admin_headers, effectiveFrom=_dt(5), expiresAt=_dt(8))
    clock.set(_dt(10))  # app was down for the whole window
    result = await SchedulerJobs(ctx).expiry_sweep()
    assert result["grantsExpired"] == 1
    assert (await _grant(ctx, item["grantId"]))["status"] == "expired"
    assert _res(ctx)["accessGroups"] == ["team"]


async def test_scheduled_owner_grant_captures_owner_at_activation(
    client, admin_headers, ctx, clock
):
    clock.set(_dt(1))
    await _group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig")
    item = await _apply(client, admin_headers, mode="owner", effectiveFrom=_dt(5))
    _res(ctx)["ownerGroup"] = "later-owner"
    clock.set(_dt(6))
    result = await SchedulerJobs(ctx).expiry_sweep()
    assert result["grantsActivated"] == 1
    grant = await _grant(ctx, item["grantId"])
    assert grant["previousOwnerGroup"] == "later-owner" and _res(ctx)["ownerGroup"] == "team"


async def test_replacing_active_grant_with_later_window(client, admin_headers, ctx, clock):
    clock.set(_dt(1))
    await _group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig", accessGroups=[])
    await _apply(client, admin_headers)
    assert "team" in _res(ctx)["accessGroups"]
    await _apply(client, admin_headers, effectiveFrom=_dt(5))
    assert "team" not in _res(ctx)["accessGroups"]  # not effective until day 5
    clock.set(_dt(6))
    await SchedulerJobs(ctx).expiry_sweep()
    assert "team" in _res(ctx)["accessGroups"]


async def test_reconcile_reapplies_access_and_reports_owner_drift(client, admin_headers, ctx):
    await _group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-a", ownerGroup="orig", accessGroups=[])
    ctx.scicat.seed_resource("dataset", "ds-o", ownerGroup="orig")
    await _apply(client, admin_headers, rid="ds-a")
    await _apply(client, admin_headers, rid="ds-o", mode="owner")
    _res(ctx, "ds-a")["accessGroups"] = []
    _res(ctx, "ds-o")["ownerGroup"] = "someone"

    result = await ReconcileService(ctx).reconcile()
    by_id = {d.resourceId: d for d in result.grantDrift}
    assert by_id["ds-a"].fixed is True and _res(ctx, "ds-a")["accessGroups"] == ["team"]
    assert by_id["ds-o"].fixed is False and _res(ctx, "ds-o")["ownerGroup"] == "someone"

    again = await ReconcileService(ctx).reconcile()
    assert [d.resourceId for d in again.grantDrift] == ["ds-o"]


async def test_reconcile_closes_grants_on_deleted_resources(client, admin_headers, ctx):
    await _group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig", accessGroups=[])
    item = await _apply(client, admin_headers)
    del ctx.scicat.resources[("dataset", "ds-1")]
    await ReconcileService(ctx).reconcile()
    grant = await _grant(ctx, item["grantId"])
    assert grant["status"] == "removed" and "no longer exists" in grant["lastError"]


async def test_cascade_delete_withdraws_grants_from_scicat(client, admin_headers, ctx):
    await _group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig", accessGroups=["keep"])
    await _apply(client, admin_headers)
    resp = await client.delete("/api/v1/groups/team?cascade=true", headers=admin_headers)
    assert resp.status_code == 204
    assert _res(ctx)["accessGroups"] == ["keep"]


async def test_retired_group_and_invalid_window_rejected(client, admin_headers, ctx, clock):
    clock.set(_dt(10))
    await _group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig", accessGroups=[])
    body = {"groupName": "team", "resourceType": "dataset", "resourceIds": ["ds-1"]}
    past = await client.post(
        "/api/v1/grants", headers=admin_headers, json={**body, "expiresAt": _dt(5).isoformat()}
    )
    assert past.status_code == 422
    await client.patch("/api/v1/groups/team", headers=admin_headers, json={"status": "retired"})
    retired = await client.post("/api/v1/grants", headers=admin_headers, json=body)
    assert retired.status_code == 409


async def test_unsupported_resource_type_rejected(client, admin_headers):
    await _group(client, admin_headers)
    for rtype in ("instrument", "job"):
        resp = await client.post(
            "/api/v1/grants",
            headers=admin_headers,
            json={"groupName": "team", "resourceType": rtype, "resourceIds": ["x"]},
        )
        assert resp.status_code == 422, rtype


async def test_removing_an_ended_grant_is_idempotent(client, admin_headers, ctx):
    await _group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig", accessGroups=[])
    item = await _apply(client, admin_headers)
    first = await client.delete(f"/api/v1/grants/{item['grantId']}", headers=admin_headers)
    second = await client.delete(f"/api/v1/grants/{item['grantId']}", headers=admin_headers)
    assert first.status_code == second.status_code == 204
    assert await ctx.app_db.audit_log.count_documents({"action": "grant.remove"}) == 1
