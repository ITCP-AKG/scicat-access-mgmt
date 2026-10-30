"""Project-level sharing and moves: a catorga project is a proposal plus the samples,
datasets and blocks linked to it. A project grant shares all records the project's group
owns, keeps covering records added later, and is withdrawn as a whole; moving the project
to another group moves those records (and attachments) along."""

from datetime import timedelta

import pytest

from app.scheduler.jobs import SchedulerJobs

pytestmark = pytest.mark.asyncio

SAMPLE_BASE = "sampleCharacteristics"


async def _group(client, admin_headers, name, managers=()):
    resp = await client.post(
        "/api/v1/groups",
        headers=admin_headers,
        json={"name": name, "category": "research-group", "managers": list(managers)},
    )
    assert resp.status_code == 201, resp.text


def _sample(ctx, sid, proposal, owner="team", **fields):
    ctx.scicat.seed_resource(
        "sample", sid, ownerGroup=owner, accessGroups=[],
        **{SAMPLE_BASE: {"SampleBase": {"proposal": proposal}}}, **fields,
    )


def _seed_project(ctx):
    ctx.scicat.seed_resource("proposal", "P", ownerGroup="team", accessGroups=[], title="P")
    _sample(ctx, "s1", "P")
    _sample(ctx, "s-other", "P", owner="other")  # linked, but another group's
    _sample(ctx, "s-q", "Q")  # another project
    ctx.scicat.seed_resource("dataset", "d1", proposalId="P", ownerGroup="team", accessGroups=[])
    ctx.scicat.seed_resource("dataset", "d-q", proposalId="Q", ownerGroup="team", accessGroups=[])
    ctx.scicat.seed_resource("origdatablock", "b1", datasetId="d1", ownerGroup="team", accessGroups=[])


async def _share(client, headers, group="partners", **extra):
    return await client.post(
        "/api/v1/grants",
        headers=headers,
        json={"groupName": group, "resourceType": "project", "resourceIds": ["P"], **extra},
    )


def _access(ctx, rtype, rid):
    return ctx.scicat.resources[(rtype, rid)]["accessGroups"]


async def _setup(client, admin_headers, ctx):
    await _group(client, admin_headers, "team", managers=["user-id"])  # alice manages team
    await _group(client, admin_headers, "partners", managers=["bob-id"])
    _seed_project(ctx)


async def test_project_grant_shares_the_projects_records(client, admin_headers, user_headers, ctx):
    await _setup(client, admin_headers, ctx)
    resp = await _share(client, user_headers)
    assert resp.status_code == 207 and resp.json()["items"][0]["ok"], resp.text

    for rtype, rid in [("proposal", "P"), ("sample", "s1"), ("dataset", "d1"), ("origdatablock", "b1")]:
        assert "partners" in _access(ctx, rtype, rid), rid
    for rtype, rid in [("sample", "s-other"), ("sample", "s-q"), ("dataset", "d-q")]:
        assert "partners" not in _access(ctx, rtype, rid), rid

    listed = (await client.get("/api/v1/grants?groupName=partners", headers=user_headers)).json()
    assert [(g["resourceType"], g["childCount"]) for g in listed] == [("project", 4)]
    children = await client.get(
        f"/api/v1/grants?parentGrantId={listed[0]['id']}", headers=user_headers
    )
    assert {(g["resourceType"], g["resourceId"]) for g in children.json()} == {
        ("proposal", "P"), ("sample", "s1"), ("dataset", "d1"), ("origdatablock", "b1")
    }


async def test_records_added_later_are_covered(client, admin_headers, user_headers, bob_headers, ctx):
    await _setup(client, admin_headers, ctx)
    await _share(client, user_headers)

    _sample(ctx, "s2", "P")  # catorga creates a sample, then asks for a sync
    resp = await client.post("/api/v1/projects/P/sync", headers=bob_headers)
    assert resp.status_code == 200 and resp.json() == {"recordsAdded": 1}
    assert "partners" in _access(ctx, "sample", "s2")

    ctx.scicat.seed_resource("dataset", "d2", proposalId="P", ownerGroup="team", accessGroups=[])
    result = await SchedulerJobs(ctx).project_cascade()  # the periodic job
    assert result["recordsAdded"] == 1
    assert "partners" in _access(ctx, "dataset", "d2")


async def test_removing_the_project_grant_withdraws_it_whole(
    client, admin_headers, user_headers, bob_headers, ctx
):
    await _setup(client, admin_headers, ctx)
    ctx.scicat.resources[("dataset", "d1")]["accessGroups"] = ["partners"]  # shared before
    grant_id = (await _share(client, user_headers)).json()["items"][0]["grantId"]

    child = (await client.get(f"/api/v1/grants?parentGrantId={grant_id}", headers=user_headers)).json()[0]
    assert (await client.delete(f"/api/v1/grants/{child['id']}", headers=user_headers)).status_code == 409

    # the receiving group's manager may give it back
    assert (await client.delete(f"/api/v1/grants/{grant_id}", headers=bob_headers)).status_code == 204
    for rtype, rid in [("proposal", "P"), ("sample", "s1"), ("origdatablock", "b1")]:
        assert "partners" not in _access(ctx, rtype, rid), rid
    assert "partners" in _access(ctx, "dataset", "d1")  # it had access before the grant
    statuses = {g["status"] async for g in ctx.app_db.resource_grants.find({"parentGrantId": grant_id})}
    assert statuses == {"removed"}


async def test_only_the_owner_side_shares_a_project(client, admin_headers, bob_headers, ctx):
    await _setup(client, admin_headers, ctx)
    resp = await _share(client, bob_headers)  # bob manages partners, not team
    item = resp.json()["items"][0]
    assert item["ok"] is False and "forbidden" in item["error"]
    assert "partners" not in _access(ctx, "proposal", "P")


async def test_a_project_is_shared_in_access_mode_only(client, admin_headers, ctx):
    await _setup(client, admin_headers, ctx)
    resp = await _share(client, admin_headers, mode="owner")
    assert resp.status_code == 422


async def test_scheduled_project_grant_follows_its_window(client, admin_headers, user_headers, ctx, clock):
    await _setup(client, admin_headers, ctx)
    start = clock() + timedelta(days=1)
    await _share(
        client, user_headers,
        effectiveFrom=start.isoformat(), expiresAt=(start + timedelta(days=1)).isoformat(),
    )
    assert "partners" not in _access(ctx, "sample", "s1")

    clock.set(start + timedelta(hours=1))
    await SchedulerJobs(ctx).expiry_sweep()
    assert "partners" in _access(ctx, "sample", "s1")

    clock.set(start + timedelta(days=2))
    await SchedulerJobs(ctx).expiry_sweep()
    assert "partners" not in _access(ctx, "sample", "s1")
    assert "partners" not in _access(ctx, "proposal", "P")


async def test_moving_a_project_moves_its_records(client, admin_headers, user_headers, ctx):
    await _setup(client, admin_headers, ctx)
    await _group(client, admin_headers, "team2", managers=["user-id"])
    ctx.scicat.seed_attachment("proposal", "P", "a1", ownerGroup="team")
    ctx.scicat.seed_attachment("sample", "s1", "a2", ownerGroup="team")
    grant_id = (await _share(client, user_headers)).json()["items"][0]["grantId"]

    resp = await client.patch("/api/v1/proposals/P", headers=user_headers, json={"ownerGroup": "team2"})
    assert resp.status_code == 200, resp.text
    for rtype, rid in [("proposal", "P"), ("sample", "s1"), ("dataset", "d1"), ("origdatablock", "b1")]:
        assert ctx.scicat.resources[(rtype, rid)]["ownerGroup"] == "team2", rid
    assert ctx.scicat.resources[("sample", "s-other")]["ownerGroup"] == "other"
    assert ctx.scicat.resources[("dataset", "d-q")]["ownerGroup"] == "team"
    assert ctx.scicat.attachments[("proposal", "P")][0]["ownerGroup"] == "team2"
    assert ctx.scicat.attachments[("sample", "s1")][0]["ownerGroup"] == "team2"

    move = await ctx.app_db.project_moves.find_one({"proposalId": "P"})
    assert move["status"] == "done" and move["moved"] == 5  # 3 records + 2 attachments
    # the project's sharing now belongs to the new owner side
    parent = await ctx.app_db.resource_grants.find_one({"id": grant_id})
    assert parent["resourceOwnerGroup"] == "team2"
    assert await ctx.app_db.audit_log.find_one({"action": "project.move"})


async def test_refused_records_of_a_move_are_retried(client, admin_headers, user_headers, ctx):
    await _setup(client, admin_headers, ctx)
    await _group(client, admin_headers, "team2", managers=["user-id"])
    ctx.scicat.fail_patch_ids.add("d1")
    resp = await client.patch("/api/v1/proposals/P", headers=user_headers, json={"ownerGroup": "team2"})
    assert resp.status_code == 200
    move = await ctx.app_db.project_moves.find_one({"proposalId": "P"})
    assert move["status"] == "incomplete" and any("d1" in f for f in move["failed"])
    assert ctx.scicat.resources[("dataset", "d1")]["ownerGroup"] == "team"

    ctx.scicat.fail_patch_ids.clear()
    result = await SchedulerJobs(ctx).project_cascade()
    assert result["movesRetried"] == 1
    assert ctx.scicat.resources[("dataset", "d1")]["ownerGroup"] == "team2"
    assert ctx.scicat.resources[("origdatablock", "b1")]["ownerGroup"] == "team2"
    move = await ctx.app_db.project_moves.find_one({"proposalId": "P"})
    assert move["status"] == "done"
