"""US4 resource grants: bulk apply (207, partial-failure isolation), owner-mode
previousOwnerGroup capture, and grant removal (T032, quickstart V4, SC-006)."""

import pytest

pytestmark = pytest.mark.asyncio


async def _make_group(client, headers, name="team"):
    await client.post(
        "/api/v1/groups", headers=headers, json={"name": name, "category": "research-group"}
    )


async def test_bulk_access_grant_applies_and_reports_per_item(client, admin_headers, ctx):
    await _make_group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig", accessGroups=["x"])
    ctx.scicat.seed_resource("dataset", "ds-2", ownerGroup="orig", accessGroups=[])

    resp = await client.post(
        "/api/v1/grants",
        headers=admin_headers,
        json={
            "groupName": "team",
            "resourceType": "dataset",
            "resourceIds": ["ds-1", "ds-2"],
            "mode": "access",
        },
    )
    assert resp.status_code == 207
    body = resp.json()
    assert body["total"] == 2 and body["succeeded"] == 2 and body["failed"] == 0
    assert {i["resourceId"] for i in body["items"]} == {"ds-1", "ds-2"}

    assert "team" in ctx.scicat.resources[("dataset", "ds-1")]["accessGroups"]
    assert "x" in ctx.scicat.resources[("dataset", "ds-1")]["accessGroups"]
    assert ctx.scicat.resources[("dataset", "ds-2")]["accessGroups"] == ["team"]


async def test_partial_failure_is_isolated(client, admin_headers, ctx):
    await _make_group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-ok", ownerGroup="orig", accessGroups=[])
    # ds-bad is not seeded -> get_resource raises -> that item fails, the other still applies
    resp = await client.post(
        "/api/v1/grants",
        headers=admin_headers,
        json={
            "groupName": "team",
            "resourceType": "dataset",
            "resourceIds": ["ds-ok", "ds-bad"],
            "mode": "access",
        },
    )
    assert resp.status_code == 207
    body = resp.json()
    assert body["succeeded"] == 1 and body["failed"] == 1
    by_id = {i["resourceId"]: i for i in body["items"]}
    assert by_id["ds-ok"]["ok"] is True
    assert by_id["ds-bad"]["ok"] is False and by_id["ds-bad"]["error"]
    assert "team" in ctx.scicat.resources[("dataset", "ds-ok")]["accessGroups"]


async def test_owner_mode_captures_previous_owner_and_remove_restores(
    client, admin_headers, ctx
):
    await _make_group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig-owner", accessGroups=[])

    resp = await client.post(
        "/api/v1/grants",
        headers=admin_headers,
        json={
            "groupName": "team",
            "resourceType": "dataset",
            "resourceIds": ["ds-1"],
            "mode": "owner",
        },
    )
    assert resp.status_code == 207
    grant_id = resp.json()["items"][0]["grantId"]
    assert ctx.scicat.resources[("dataset", "ds-1")]["ownerGroup"] == "team"

    grants = (await client.get("/api/v1/grants", headers=admin_headers)).json()
    grant = next(g for g in grants if g["id"] == grant_id)
    assert grant["previousOwnerGroup"] == "orig-owner"

    # removal withdraws the grant and restores the prior owner
    rm = await client.delete(f"/api/v1/grants/{grant_id}", headers=admin_headers)
    assert rm.status_code == 204
    assert ctx.scicat.resources[("dataset", "ds-1")]["ownerGroup"] == "orig-owner"


async def test_remove_access_grant_withdraws_group(client, admin_headers, ctx):
    await _make_group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig", accessGroups=["keep"])
    resp = await client.post(
        "/api/v1/grants",
        headers=admin_headers,
        json={
            "groupName": "team",
            "resourceType": "dataset",
            "resourceIds": ["ds-1"],
            "mode": "access",
        },
    )
    grant_id = resp.json()["items"][0]["grantId"]
    await client.delete(f"/api/v1/grants/{grant_id}", headers=admin_headers)
    access = ctx.scicat.resources[("dataset", "ds-1")]["accessGroups"]
    assert "team" not in access and "keep" in access


async def test_apply_unknown_group_404(client, admin_headers, ctx):
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig", accessGroups=[])
    resp = await client.post(
        "/api/v1/grants",
        headers=admin_headers,
        json={
            "groupName": "ghost",
            "resourceType": "dataset",
            "resourceIds": ["ds-1"],
            "mode": "access",
        },
    )
    assert resp.status_code == 404


async def test_apply_requires_admin_or_manager(client, user_headers, ctx, admin_headers):
    await _make_group(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig", accessGroups=[])
    resp = await client.post(
        "/api/v1/grants",
        headers=user_headers,
        json={
            "groupName": "team",
            "resourceType": "dataset",
            "resourceIds": ["ds-1"],
            "mode": "access",
        },
    )
    assert resp.status_code == 403


async def test_browse_resources_lists_and_filters(client, admin_headers, ctx):
    ctx.scicat.seed_resource(
        "dataset", "ds-1", datasetName="Alpha", ownerGroup="g1", accessGroups=[]
    )
    ctx.scicat.seed_resource(
        "dataset", "ds-2", datasetName="Beta", ownerGroup="g2", accessGroups=[]
    )
    resp = await client.get("/api/v1/resources/dataset", headers=admin_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert {i["label"] for i in items} == {"Alpha", "Beta"}

    filtered = await client.get(
        "/api/v1/resources/dataset?ownerGroup=g1", headers=admin_headers
    )
    fitems = filtered.json()["items"]
    assert len(fitems) == 1 and fitems[0]["id"] == "ds-1"
