"""Input-validation and data-hygiene regressions: escaped searches, exact username
collision, temporal-window validation, ended memberships, audit actor names and the
startup migration."""

from datetime import datetime, timezone

import pytest

from app.db import migrate

pytestmark = pytest.mark.asyncio


def _dt(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=timezone.utc)


async def _make_group(client, headers, name="team", **extra):
    return await client.post(
        "/api/v1/groups",
        headers=headers,
        json={"name": name, "category": "research-group", **extra},
    )


async def test_group_search_escapes_regex(client, admin_headers):
    await _make_group(client, admin_headers, "ab", description="reactor (main)")
    await _make_group(client, admin_headers, "a1b")
    resp = await client.get("/api/v1/groups", headers=admin_headers, params={"q": "(main"})
    assert resp.status_code == 200
    assert [g["name"] for g in resp.json()] == ["ab"]
    # "." is literal, not "any character"
    dotted = await client.get("/api/v1/groups", headers=admin_headers, params={"q": "a.b"})
    assert dotted.json() == []


async def test_group_name_rules(client, admin_headers):
    for bad in ("a/b", "with space", "-lead", "x" * 65):
        assert (await _make_group(client, admin_headers, bad)).status_code == 422, bad


async def test_username_collision_is_exact(client, admin_headers):
    assert (await _make_group(client, admin_headers, "ALICE")).status_code == 409
    assert (await _make_group(client, admin_headers, "ali")).status_code == 201


async def test_membership_window_validated(client, admin_headers, clock):
    clock.set(_dt(10))
    await _make_group(client, admin_headers)
    past = await client.post(
        "/api/v1/groups/team/members",
        headers=admin_headers,
        json={"userId": "user-id", "expiresAt": _dt(5).isoformat()},
    )
    assert past.status_code == 422
    inverted = await client.post(
        "/api/v1/groups/team/members",
        headers=admin_headers,
        json={
            "userId": "user-id",
            "effectiveFrom": _dt(20).isoformat(),
            "expiresAt": _dt(15).isoformat(),
        },
    )
    assert inverted.status_code == 422


async def test_readd_after_unswept_expiry(client, admin_headers, clock, ctx):
    clock.set(_dt(1))
    await _make_group(client, admin_headers)
    first = await client.post(
        "/api/v1/groups/team/members",
        headers=admin_headers,
        json={"userId": "user-id", "expiresAt": _dt(5).isoformat()},
    )
    clock.set(_dt(10))  # lapsed, but no sweep has run
    again = await client.post(
        "/api/v1/groups/team/members", headers=admin_headers, json={"userId": "user-id"}
    )
    assert again.status_code == 201
    old = await ctx.app_db.memberships.find_one({"id": first.json()["id"]})
    assert old["status"] == "expired"


async def test_ended_membership_cannot_be_resurrected(client, admin_headers):
    await _make_group(client, admin_headers)
    mid = (
        await client.post(
            "/api/v1/groups/team/members", headers=admin_headers, json={"userId": "user-id"}
        )
    ).json()["id"]
    await client.delete(f"/api/v1/memberships/{mid}", headers=admin_headers)
    resp = await client.patch(
        f"/api/v1/memberships/{mid}", headers=admin_headers, json={"expiresAt": None}
    )
    assert resp.status_code == 409


async def test_membership_update_extends_expiry(client, admin_headers, clock):
    clock.set(_dt(1))
    await _make_group(client, admin_headers)
    mid = (
        await client.post(
            "/api/v1/groups/team/members",
            headers=admin_headers,
            json={"userId": "user-id", "expiresAt": _dt(5).isoformat()},
        )
    ).json()["id"]
    resp = await client.patch(
        f"/api/v1/memberships/{mid}", headers=admin_headers, json={"expiresAt": _dt(20).isoformat()}
    )
    assert resp.status_code == 200 and resp.json()["status"] == "active"


async def test_audit_records_actor_name(client, admin_headers, user_headers):
    await _make_group(client, admin_headers, managers=["user-id"])
    await client.patch("/api/v1/groups/team", headers=user_headers, json={"description": "x"})
    entries = (
        await client.get("/api/v1/audit", headers=admin_headers, params={"entityType": "group"})
    ).json()
    update = next(e for e in entries if e["action"] == "group.update")
    assert update["actor"] == "user-id" and update["actorName"] == "alice"


async def test_startup_migration(ctx):
    await ctx.app_db.groups.insert_one({"name": "p1", "category": "proposal"})
    await ctx.app_db.resource_grants.insert_one(
        {"id": "g1", "groupName": "p1", "resourceType": "instrument", "resourceId": "i1",
         "status": "scheduled"}
    )
    await migrate(ctx.app_db)
    await migrate(ctx.app_db)  # idempotent
    assert (await ctx.app_db.groups.find_one({"name": "p1"}))["category"] == "administrative"
    assert (await ctx.app_db.resource_grants.find_one({"id": "g1"}))["status"] == "removed"


async def test_get_single_user(client, admin_headers):
    resp = await client.get("/api/v1/users/user-id", headers=admin_headers)
    assert resp.status_code == 200 and resp.json()["username"] == "alice"
    assert (await client.get("/api/v1/users/ghost", headers=admin_headers)).status_code == 404
