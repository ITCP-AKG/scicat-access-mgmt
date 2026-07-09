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
