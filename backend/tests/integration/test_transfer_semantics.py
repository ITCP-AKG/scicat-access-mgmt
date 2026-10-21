"""Ownership-transfer regressions (Phase 5): only personally owned resources move,
rules match the groups the user had, failed/pending transfers can be retried, every
departure is its own batch, and deactivation really removes access."""

from datetime import datetime, timezone

import pytest

from app.scheduler.jobs import SchedulerJobs

pytestmark = pytest.mark.asyncio


def _dt(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=timezone.utc)


async def _group(client, headers, name, category="research-group"):
    resp = await client.post(
        "/api/v1/groups", headers=headers, json={"name": name, "category": category}
    )
    assert resp.status_code == 201, resp.text


async def _rule(client, headers, **overrides):
    body = {
        "name": "handover",
        "match": {},
        "successorType": "group",
        "successor": "successor-team",
        "transferOwner": False,
        "priority": 10,
        "enabled": True,
    }
    body.update(overrides)
    resp = await client.post("/api/v1/transfer-rules", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _deactivate(client, headers, user_id="user-id"):
    resp = await client.post(f"/api/v1/users/{user_id}/deactivate", headers=headers)
    assert resp.status_code == 202, resp.text
    return resp.json()


def _res(ctx, rid, rtype="dataset"):
    return ctx.scicat.resources[(rtype, rid)]


async def test_shared_group_data_is_never_transferred(client, admin_headers, ctx):
    """C7: alice also carries an unmanaged lab group; its data must stay put."""
    await ctx.scicat_db["UserIdentity"].update_one(
        {"userId": "user-id"}, {"$push": {"profile.accessGroups": "AKG"}}
    )
    await _group(client, admin_headers, "successor-team")
    await _rule(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "lab-data", ownerGroup="AKG", owner="carol")
    ctx.scicat.seed_resource("dataset", "mine", ownerGroup="u.alice", owner="carol")

    body = await _deactivate(client, admin_headers)
    assert [r["resourceId"] for r in body["records"]] == ["mine"]
    assert _res(ctx, "lab-data")["ownerGroup"] == "AKG"
    assert _res(ctx, "mine")["ownerGroup"] == "successor-team"


async def test_expiry_transfer_matches_group_scoped_rule(client, admin_headers, ctx, clock):
    """H7: the rule is scoped to the group that just lapsed (already projected away)."""
    clock.set(_dt(1))
    await _group(client, admin_headers, "team")
    await _group(client, admin_headers, "successor-team")
    await _rule(client, admin_headers, match={"groupName": "team"})
    await client.post(
        "/api/v1/groups/team/members",
        headers=admin_headers,
        json={"userId": "user-id", "expiresAt": _dt(5).isoformat()},
    )
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="u.alice")

    clock.set(_dt(10))
    result = await SchedulerJobs(ctx).expiry_sweep()
    assert result["transferRecords"] == 1
    assert _res(ctx, "ds-1")["ownerGroup"] == "successor-team"
    departures = (await client.get("/api/v1/transfer-batches", headers=admin_headers)).json()
    assert departures[0]["reason"] == "expiry" and departures[0]["groups"] == ["team"]


async def test_expiry_transfer_matches_category_rule(client, admin_headers, ctx, clock):
    clock.set(_dt(1))
    await _group(client, admin_headers, "proj-x", category="project")
    await _group(client, admin_headers, "successor-team")
    await _rule(client, admin_headers, match={"category": "project"})
    await client.post(
        "/api/v1/groups/proj-x/members",
        headers=admin_headers,
        json={"userId": "user-id", "expiresAt": _dt(5).isoformat()},
    )
    ctx.scicat.seed_resource("sample", "s-1", ownerGroup="u.alice", owner="alice")
    clock.set(_dt(10))
    await SchedulerJobs(ctx).expiry_sweep()
    assert _res(ctx, "s-1", "sample")["ownerGroup"] == "successor-team"
    assert _res(ctx, "s-1", "sample")["owner"] == "alice"  # group successor: contact kept


async def test_no_expiry_transfer_while_other_memberships_remain(
    client, admin_headers, ctx, clock
):
    clock.set(_dt(1))
    await _group(client, admin_headers, "team")
    await _group(client, admin_headers, "other")
    await _group(client, admin_headers, "successor-team")
    await _rule(client, admin_headers)
    await client.post(
        "/api/v1/groups/team/members",
        headers=admin_headers,
        json={"userId": "user-id", "expiresAt": _dt(5).isoformat()},
    )
    await client.post("/api/v1/groups/other/members", headers=admin_headers, json={"userId": "user-id"})
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="u.alice")
    clock.set(_dt(10))
    result = await SchedulerJobs(ctx).expiry_sweep()
    assert result["transferRecords"] == 0
    assert _res(ctx, "ds-1")["ownerGroup"] == "u.alice"


async def test_failed_transfer_can_be_retried(client, admin_headers, ctx):
    """H8: a failed reassignment is retried in place, never duplicated."""
    await _group(client, admin_headers, "successor-team")
    await _rule(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="u.alice")
    ctx.scicat.fail_patch_ids.add("ds-1")

    body = await _deactivate(client, admin_headers)
    record = body["records"][0]
    assert record["outcome"] == "failed" and record["error"]

    ctx.scicat.fail_patch_ids.clear()
    retry = await client.post(
        f"/api/v1/transfer-batches/{body['batchId']}/retry", headers=admin_headers
    )
    assert retry.status_code == 200
    again = retry.json()["records"][0]
    assert again["outcome"] == "transferred" and again["id"] == record["id"]
    assert _res(ctx, "ds-1")["ownerGroup"] == "successor-team"

    records = (
        await client.get(f"/api/v1/transfer-records?batchId={body['batchId']}", headers=admin_headers)
    ).json()
    assert len(records) == 1
    # a further retry has nothing left to do
    third = await client.post(
        f"/api/v1/transfer-batches/{body['batchId']}/retry", headers=admin_headers
    )
    assert third.json()["records"] == []


async def test_pending_then_rule_added_then_retry(client, admin_headers, ctx):
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="u.alice")
    body = await _deactivate(client, admin_headers)
    assert body["records"][0]["outcome"] == "pending_manual"
    assert _res(ctx, "ds-1")["ownerGroup"] == "u.alice"

    await _group(client, admin_headers, "successor-team")
    await _rule(client, admin_headers)
    retry = await client.post(
        f"/api/v1/transfer-batches/{body['batchId']}/retry", headers=admin_headers
    )
    assert retry.json()["records"][0]["outcome"] == "transferred"


async def test_pending_fixed_by_hand_becomes_resolved(client, admin_headers, ctx):
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="u.alice")
    body = await _deactivate(client, admin_headers)
    _res(ctx, "ds-1")["ownerGroup"] = "handled-manually"
    retry = await client.post(
        f"/api/v1/transfer-batches/{body['batchId']}/retry", headers=admin_headers
    )
    rec = retry.json()["records"][0]
    assert rec["outcome"] == "resolved"


async def test_each_departure_is_its_own_batch(client, admin_headers, ctx):
    """H8: re-hired and leaving again transfers what was created in between."""
    await _group(client, admin_headers, "team")
    await _group(client, admin_headers, "successor-team")
    await _rule(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "old", ownerGroup="u.alice")
    first = await _deactivate(client, admin_headers)

    await client.post("/api/v1/groups/team/members", headers=admin_headers, json={"userId": "user-id"})
    assert not await ctx.app_db.departed_users.find_one({"_id": "user-id"})  # re-joined
    ctx.scicat.seed_resource("dataset", "new", ownerGroup="u.alice")
    second = await _deactivate(client, admin_headers)
    assert second["batchId"] != first["batchId"]
    assert [r["resourceId"] for r in second["records"]] == ["new"]


async def test_deactivate_ends_memberships_and_access(client, admin_headers, ctx):
    """H9: a departed user must not keep app-managed access."""
    await _group(client, admin_headers, "team")
    await client.post("/api/v1/groups/team/members", headers=admin_headers, json={"userId": "user-id"})
    doc = await ctx.scicat_db["UserIdentity"].find_one({"userId": "user-id"})
    assert "team" in doc["profile"]["accessGroups"]

    await _deactivate(client, admin_headers)
    doc = await ctx.scicat_db["UserIdentity"].find_one({"userId": "user-id"})
    assert "team" not in doc["profile"]["accessGroups"]
    members = (await client.get("/api/v1/groups/team/members", headers=admin_headers)).json()
    assert members[0]["status"] == "revoked"


async def test_deactivate_unknown_user_404(client, admin_headers):
    resp = await client.post("/api/v1/users/ghost/deactivate", headers=admin_headers)
    assert resp.status_code == 404


async def test_transfer_pages_through_all_owned_resources(client, admin_headers, ctx):
    """C6: SciCat caps list pages at 100; every owned resource must still move."""
    await _group(client, admin_headers, "successor-team")
    await _rule(client, admin_headers)
    for i in range(150):
        ctx.scicat.seed_resource("dataset", f"ds-{i:03d}", ownerGroup="u.alice")
    body = await _deactivate(client, admin_headers)
    assert len(body["records"]) == 150
    assert all(_res(ctx, f"ds-{i:03d}")["ownerGroup"] == "successor-team" for i in range(150))


async def test_contact_only_with_group_successor_is_pending(client, admin_headers, ctx):
    await _group(client, admin_headers, "successor-team")
    await _rule(client, admin_headers)
    # project data: owned by a project group, alice only the contact
    ctx.scicat.seed_resource(
        "dataset", "proj", ownerGroup="project-x", owner="alice", contactEmail="alice@catorga.dev"
    )
    body = await _deactivate(client, admin_headers)
    rec = body["records"][0]
    assert rec["outcome"] == "pending_manual"
    assert any("contact" in n for n in rec["notes"])
    assert _res(ctx, "proj")["ownerGroup"] == "project-x"


async def test_contact_handover_to_user_successor(client, admin_headers, ctx):
    await _rule(client, admin_headers, successorType="user", successor="bob-id", transferOwner=True)
    ctx.scicat.seed_resource(
        "dataset", "proj", ownerGroup="project-x", owner="alice", contactEmail="alice@catorga.dev"
    )
    ctx.scicat.seed_resource(
        "proposal", "P-1", ownerGroup="project-x", email="alice@catorga.dev",
        firstname="Alice", lastname="Researcher", pi_email="boss@catorga.dev",
    )
    ctx.scicat.seed_resource("sample", "s-1", ownerGroup="project-x", owner="alice")
    body = await _deactivate(client, admin_headers)
    assert {r["outcome"] for r in body["records"]} == {"transferred"}

    ds = _res(ctx, "proj")
    assert (ds["ownerGroup"], ds["owner"], ds["contactEmail"]) == (
        "project-x", "bob", "bob@catorga.dev"
    )
    prop = _res(ctx, "P-1", "proposal")
    assert (prop["email"], prop["firstname"], prop["lastname"]) == (
        "bob@catorga.dev", "Bob", "Postdoc"
    )
    assert prop["pi_email"] == "boss@catorga.dev"
    assert _res(ctx, "s-1", "sample")["owner"] == "bob"


async def test_without_template_owner_groups_are_left_alone(client, admin_headers, ctx):
    ctx.settings.personal_group_template = ""
    await _group(client, admin_headers, "successor-team")
    await _rule(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="u.alice")
    body = await _deactivate(client, admin_headers)
    assert body["records"] == []
    assert _res(ctx, "ds-1")["ownerGroup"] == "u.alice"


async def test_rule_validation(client, admin_headers):
    bad_user = await client.post(
        "/api/v1/transfer-rules",
        headers=admin_headers,
        json={"name": "x", "successorType": "user", "successor": "nobody"},
    )
    assert bad_user.status_code == 422
    reserved = await client.post(
        "/api/v1/transfer-rules",
        headers=admin_headers,
        json={"name": "x", "successorType": "group", "successor": "admin"},
    )
    assert reserved.status_code == 422


async def test_failed_batches_are_retried_by_reconcile_job(client, admin_headers, ctx):
    await _group(client, admin_headers, "successor-team")
    await _rule(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="u.alice")
    ctx.scicat.fail_patch_ids.add("ds-1")
    body = await _deactivate(client, admin_headers)
    departure = await ctx.app_db.departures.find_one({"id": body["batchId"]})
    assert departure["needsRetry"] is True

    ctx.scicat.fail_patch_ids.clear()
    await SchedulerJobs(ctx).reconcile()
    assert _res(ctx, "ds-1")["ownerGroup"] == "successor-team"
    departure = await ctx.app_db.departures.find_one({"id": body["batchId"]})
    assert departure["needsRetry"] is False


async def test_pending_only_batches_are_not_auto_retried(client, admin_headers, ctx):
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="u.alice")
    body = await _deactivate(client, admin_headers)
    departure = await ctx.app_db.departures.find_one({"id": body["batchId"]})
    assert departure["needsRetry"] is False
