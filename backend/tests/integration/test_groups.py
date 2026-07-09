"""US1 groups CRUD + reserved-name + delete-guard (T015, quickstart V1)."""

import pytest

pytestmark = pytest.mark.asyncio


async def test_create_and_list_group(client, admin_headers):
    resp = await client.post(
        "/api/v1/groups",
        headers=admin_headers,
        json={"name": "catalysis-team-alpha", "category": "research-group", "description": "Team A"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["createdBy"] == "admin-id"

    listed = await client.get("/api/v1/groups", headers=admin_headers)
    names = [g["name"] for g in listed.json()]
    assert "catalysis-team-alpha" in names


@pytest.mark.parametrize("reserved", ["admin", "globalaccess", "all"])
async def test_reserved_names_rejected(client, admin_headers, reserved):
    resp = await client.post(
        "/api/v1/groups", headers=admin_headers,
        json={"name": reserved, "category": "other"},
    )
    assert resp.status_code == 409


async def test_duplicate_rejected(client, admin_headers):
    body = {"name": "dup", "category": "other"}
    assert (await client.post("/api/v1/groups", headers=admin_headers, json=body)).status_code == 201
    assert (await client.post("/api/v1/groups", headers=admin_headers, json=body)).status_code == 409


async def test_update_group_audited(client, admin_headers):
    await client.post("/api/v1/groups", headers=admin_headers, json={"name": "g1", "category": "other"})
    resp = await client.patch(
        "/api/v1/groups/g1", headers=admin_headers, json={"description": "updated"}
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "updated"


async def test_delete_guarded_then_cascade(client, admin_headers):
    await client.post("/api/v1/groups", headers=admin_headers, json={"name": "g2", "category": "other"})
    await client.post(
        "/api/v1/groups/g2/members", headers=admin_headers, json={"userId": "user-id"}
    )
    # delete blocked while it has a member
    blocked = await client.delete("/api/v1/groups/g2", headers=admin_headers)
    assert blocked.status_code == 409
    # cascade succeeds
    ok = await client.delete("/api/v1/groups/g2?cascade=true", headers=admin_headers)
    assert ok.status_code == 204


async def test_non_admin_cannot_create(client, user_headers):
    resp = await client.post(
        "/api/v1/groups", headers=user_headers, json={"name": "x", "category": "other"}
    )
    assert resp.status_code == 403
