"""US3 projection into SciCat + intrinsic preservation + reconcile drift (T027, V3)."""

import pytest

pytestmark = pytest.mark.asyncio


async def _identity_groups(ctx, user_id):
    doc = await ctx.scicat_db["UserIdentity"].find_one({"userId": user_id})
    return (doc["profile"]["accessGroups"])


async def test_projection_adds_and_preserves(client, admin_headers, ctx):
    await client.post(
        "/api/v1/groups", headers=admin_headers, json={"name": "team", "category": "research-group"}
    )
    # adding a member auto-projects
    await client.post("/api/v1/groups/team/members", headers=admin_headers, json={"userId": "user-id"})

    groups = await _identity_groups(ctx, "user-id")
    assert "team" in groups
    # intrinsic strings preserved
    assert "u.alice" in groups
    assert "globalaccess" in groups


async def test_revoke_withdraws_but_preserves_intrinsic(client, admin_headers, ctx):
    await client.post(
        "/api/v1/groups", headers=admin_headers, json={"name": "team", "category": "research-group"}
    )
    add = await client.post(
        "/api/v1/groups/team/members", headers=admin_headers, json={"userId": "user-id"}
    )
    mid = add.json()["id"]
    await client.delete(f"/api/v1/memberships/{mid}", headers=admin_headers)

    groups = await _identity_groups(ctx, "user-id")
    assert "team" not in groups
    assert "u.alice" in groups and "globalaccess" in groups


async def test_explicit_run_and_reconcile_reports_drift(client, admin_headers, ctx):
    await client.post(
        "/api/v1/groups", headers=admin_headers, json={"name": "team", "category": "research-group"}
    )
    # seed a membership directly (no auto-projection), creating drift
    from app.models.membership import Membership

    m = Membership(groupName="team", userId="user-id", status="active")
    await ctx.app_db.memberships.insert_one(m.model_dump())

    rec = await client.post("/api/v1/projection/reconcile", headers=admin_headers)
    assert rec.status_code == 200
    body = rec.json()
    assert body["usersUpdated"] == 1
    assert any(d["userId"] == "user-id" for d in body["drift"])

    # after reconcile, a second reconcile shows no drift
    rec2 = await client.post("/api/v1/projection/reconcile", headers=admin_headers)
    assert rec2.json()["drift"] == []


async def test_projection_requires_admin(client, user_headers):
    resp = await client.post("/api/v1/projection/run", headers=user_headers, json={"all": True})
    assert resp.status_code == 403


async def _managed_team(client, admin_headers, managers=("user-id",)):
    resp = await client.post(
        "/api/v1/groups",
        headers=admin_headers,
        json={"name": "team", "category": "research-group", "managers": list(managers)},
    )
    assert resp.status_code == 201, resp.text


async def test_managers_get_member_access(client, admin_headers, ctx):
    await _managed_team(client, admin_headers)
    assert "team" in await _identity_groups(ctx, "user-id")

    # adding a manager projects them, removing one withdraws it
    await client.patch(
        "/api/v1/groups/team", headers=admin_headers, json={"managers": ["bob-id"]}
    )
    assert "team" not in await _identity_groups(ctx, "user-id")
    assert "team" in await _identity_groups(ctx, "bob-id")


async def test_retiring_or_deleting_a_group_ends_manager_access(client, admin_headers, ctx):
    await _managed_team(client, admin_headers)
    await client.patch("/api/v1/groups/team", headers=admin_headers, json={"status": "retired"})
    assert "team" not in await _identity_groups(ctx, "user-id")
    await client.patch("/api/v1/groups/team", headers=admin_headers, json={"status": "active"})
    assert "team" in await _identity_groups(ctx, "user-id")

    resp = await client.delete("/api/v1/groups/team", headers=admin_headers)
    assert resp.status_code == 204, resp.text
    assert "team" not in await _identity_groups(ctx, "user-id")


async def test_reconcile_restores_manager_access(client, admin_headers, ctx):
    await _managed_team(client, admin_headers)
    # a SciCat login rewrites accessGroups without app-managed groups
    await ctx.scicat_db["UserIdentity"].update_one(
        {"userId": "user-id"}, {"$set": {"profile.accessGroups": ["u.alice"]}}
    )
    await client.post("/api/v1/projection/reconcile", headers=admin_headers)
    assert "team" in await _identity_groups(ctx, "user-id")


async def test_deactivation_ends_manager_access(client, admin_headers, ctx):
    await _managed_team(client, admin_headers)
    resp = await client.post("/api/v1/users/user-id/deactivate", headers=admin_headers)
    assert resp.status_code == 202, resp.text
    assert "team" not in await _identity_groups(ctx, "user-id")
    group = await ctx.app_db.groups.find_one({"name": "team"})
    assert group["managers"] == []


async def _reactivations(ctx, user_id):
    return await ctx.app_db.audit_log.count_documents(
        {"action": "user.reactivate", "entityId": user_id}
    )


async def test_departed_user_made_manager_is_reactivated(client, admin_headers, ctx):
    resp = await client.post("/api/v1/users/user-id/deactivate", headers=admin_headers)
    assert resp.status_code == 202, resp.text
    assert await ctx.app_db.departed_users.find_one({"_id": "user-id"})

    await _managed_team(client, admin_headers)
    assert not await ctx.app_db.departed_users.find_one({"_id": "user-id"})
    assert await _reactivations(ctx, "user-id") == 1
    assert "team" in await _identity_groups(ctx, "user-id")


async def test_departed_user_added_as_manager_is_reactivated(client, admin_headers, ctx):
    await _managed_team(client, admin_headers, managers=())
    resp = await client.post("/api/v1/users/user-id/deactivate", headers=admin_headers)
    assert resp.status_code == 202, resp.text

    resp = await client.patch(
        "/api/v1/groups/team", headers=admin_headers, json={"managers": ["user-id"]}
    )
    assert resp.status_code == 200, resp.text
    assert not await ctx.app_db.departed_users.find_one({"_id": "user-id"})
    assert await _reactivations(ctx, "user-id") == 1
    assert "team" in await _identity_groups(ctx, "user-id")
