"""US2 membership add/list/remove + user->groups + last-admin guard (T021, V2/V8)."""

import pytest

pytestmark = pytest.mark.asyncio


async def _make_group(client, admin_headers, name="team"):
    await client.post(
        "/api/v1/groups", headers=admin_headers, json={"name": name, "category": "research-group"}
    )


async def test_add_list_remove_member(client, admin_headers):
    await _make_group(client, admin_headers)
    add = await client.post(
        "/api/v1/groups/team/members", headers=admin_headers, json={"userId": "user-id"}
    )
    assert add.status_code == 201, add.text
    mid = add.json()["id"]

    members = await client.get("/api/v1/groups/team/members", headers=admin_headers)
    assert [m["userId"] for m in members.json()] == ["user-id"]

    user_groups = await client.get("/api/v1/users/user-id/groups", headers=admin_headers)
    assert "team" in [m["groupName"] for m in user_groups.json()]

    rm = await client.delete(f"/api/v1/memberships/{mid}", headers=admin_headers)
    assert rm.status_code == 204


async def test_duplicate_member_rejected(client, admin_headers):
    await _make_group(client, admin_headers)
    await client.post("/api/v1/groups/team/members", headers=admin_headers, json={"userId": "user-id"})
    dup = await client.post(
        "/api/v1/groups/team/members", headers=admin_headers, json={"userId": "user-id"}
    )
    assert dup.status_code == 409


async def test_unknown_user_rejected(client, admin_headers):
    await _make_group(client, admin_headers)
    resp = await client.post(
        "/api/v1/groups/team/members", headers=admin_headers, json={"userId": "ghost"}
    )
    assert resp.status_code == 404


async def test_search_users(client, admin_headers):
    resp = await client.get("/api/v1/users?q=alice", headers=admin_headers)
    assert resp.status_code == 200
    assert any(u["username"] == "alice" for u in resp.json())


async def test_last_admin_lockout(ctx):
    """Directly seed a membership in the configured admin group and assert revoke is blocked."""
    from app.models.membership import Membership
    from app.services.memberships import LastAdminError, MembershipService

    m = Membership(groupName="admin", userId="user-id", status="active")
    await ctx.app_db.memberships.insert_one(m.model_dump())
    svc = MembershipService(ctx)
    with pytest.raises(LastAdminError):
        await svc.revoke(m.id, actor="admin-id")
