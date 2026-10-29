"""Proposal create/update proxy: SciCat only lets `admin`/`proposalingestor` write proposals,
so these routes decide who may — admins and managers of the ownerGroup create; members of
the ownerGroup (or its managers) edit."""

import pytest

pytestmark = pytest.mark.asyncio


async def _setup_team(client, admin_headers, managers=("user-id",)):
    resp = await client.post(
        "/api/v1/groups",
        headers=admin_headers,
        json={"name": "team", "category": "research-group", "managers": list(managers)},
    )
    assert resp.status_code == 201, resp.text


async def _join(ctx, user_id: str, group: str):
    await ctx.scicat_db["UserIdentity"].update_one(
        {"userId": user_id}, {"$addToSet": {"profile.accessGroups": group}}
    )
    ctx.whoami_cache.drop("bob-token")
    ctx.whoami_cache.drop("user-token")


def _proposal(**fields):
    return {
        "proposalId": "p-1",
        "ownerGroup": "team",
        "email": "pi@catorga.dev",
        "title": "Catalyst screening",
        **fields,
    }


async def test_admin_creates_in_any_group(client, admin_headers, ctx):
    resp = await client.post(
        "/api/v1/proposals", headers=admin_headers, json=_proposal(ownerGroup="elsewhere")
    )
    assert resp.status_code == 201, resp.text
    assert ctx.scicat.resources[("proposal", "p-1")]["ownerGroup"] == "elsewhere"


async def test_manager_creates_in_managed_group(client, admin_headers, user_headers, ctx):
    await _setup_team(client, admin_headers)
    resp = await client.post("/api/v1/proposals", headers=user_headers, json=_proposal())
    assert resp.status_code == 201, resp.text
    assert ctx.scicat.resources[("proposal", "p-1")]["title"] == "Catalyst screening"

    entries = await ctx.app_db.audit_log.find({"action": "proposal.create"}).to_list(None)
    assert len(entries) == 1 and entries[0]["entityId"] == "p-1"
    assert entries[0]["actor"] == "user-id"


async def test_manager_cannot_create_in_other_group(client, admin_headers, user_headers, ctx):
    await _setup_team(client, admin_headers)
    resp = await client.post(
        "/api/v1/proposals", headers=user_headers, json=_proposal(ownerGroup="u.bob")
    )
    assert resp.status_code == 403
    assert ("proposal", "p-1") not in ctx.scicat.resources


async def test_plain_member_cannot_create(client, admin_headers, bob_headers, ctx):
    await _setup_team(client, admin_headers)
    await _join(ctx, "bob-id", "team")
    resp = await client.post("/api/v1/proposals", headers=bob_headers, json=_proposal())
    assert resp.status_code == 403


async def test_create_drops_access_groups(client, admin_headers, user_headers, ctx):
    await _setup_team(client, admin_headers)
    resp = await client.post(
        "/api/v1/proposals", headers=user_headers, json=_proposal(accessGroups=["outsiders"])
    )
    assert resp.status_code == 201
    assert "accessGroups" not in ctx.scicat.resources[("proposal", "p-1")]


async def test_duplicate_proposal_id_is_conflict(client, admin_headers, ctx):
    ctx.scicat.seed_resource("proposal", "p-1", ownerGroup="team")
    resp = await client.post("/api/v1/proposals", headers=admin_headers, json=_proposal())
    assert resp.status_code == 409


async def test_blank_owner_group_rejected(client, admin_headers):
    resp = await client.post(
        "/api/v1/proposals", headers=admin_headers, json=_proposal(ownerGroup="  ")
    )
    assert resp.status_code == 422


async def test_owner_group_member_edits(client, admin_headers, bob_headers, ctx):
    await _setup_team(client, admin_headers)
    await _join(ctx, "bob-id", "team")
    ctx.scicat.seed_resource("proposal", "p-1", ownerGroup="team", title="old")
    resp = await client.patch(
        "/api/v1/proposals/p-1", headers=bob_headers, json={"title": "new", "proposalId": "x"}
    )
    assert resp.status_code == 200, resp.text
    assert ctx.scicat.resources[("proposal", "p-1")]["title"] == "new"
    assert ctx.scicat.patches[-1] == ("proposal", "p-1", {"title": "new"})

    entries = await ctx.app_db.audit_log.find({"action": "proposal.update"}).to_list(None)
    assert entries[0]["before"] == {"title": "old"} and entries[0]["after"] == {"title": "new"}


async def test_personal_group_owner_edits(client, bob_headers, ctx):
    ctx.scicat.seed_resource("proposal", "p-1", ownerGroup="bob", title="old")
    resp = await client.patch("/api/v1/proposals/p-1", headers=bob_headers, json={"title": "new"})
    assert resp.status_code == 200, resp.text


async def test_manager_edits_without_membership(client, admin_headers, user_headers, ctx):
    await _setup_team(client, admin_headers)
    ctx.scicat.seed_resource("proposal", "p-1", ownerGroup="team", title="old")
    resp = await client.patch("/api/v1/proposals/p-1", headers=user_headers, json={"title": "new"})
    assert resp.status_code == 200, resp.text


async def test_outsider_cannot_edit(client, admin_headers, bob_headers, ctx):
    await _setup_team(client, admin_headers)
    ctx.scicat.seed_resource("proposal", "p-1", ownerGroup="team", title="old")
    resp = await client.patch("/api/v1/proposals/p-1", headers=bob_headers, json={"title": "new"})
    assert resp.status_code == 403
    assert ctx.scicat.resources[("proposal", "p-1")]["title"] == "old"


async def test_member_cannot_move_to_unmanaged_group(client, admin_headers, bob_headers, ctx):
    await _setup_team(client, admin_headers)
    await _join(ctx, "bob-id", "team")
    ctx.scicat.seed_resource("proposal", "p-1", ownerGroup="team")
    resp = await client.patch(
        "/api/v1/proposals/p-1", headers=bob_headers, json={"ownerGroup": "u.bob"}
    )
    assert resp.status_code == 403
    assert ctx.scicat.resources[("proposal", "p-1")]["ownerGroup"] == "team"


async def test_edit_unknown_proposal_is_404(client, admin_headers):
    resp = await client.patch("/api/v1/proposals/nope", headers=admin_headers, json={"title": "x"})
    assert resp.status_code == 404


async def test_unauthenticated_rejected(client):
    resp = await client.post("/api/v1/proposals", json=_proposal())
    assert resp.status_code == 401
