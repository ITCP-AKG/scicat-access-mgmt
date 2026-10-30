"""Authorization regressions: every mutating route is limited to admins or managers of the
affected group, owner grants are admin-only, and managers share only resources owned by a
group they manage (all SciCat calls run as the service account, so the app is the only
guard)."""

import pytest

pytestmark = pytest.mark.asyncio


async def _setup_team(client, admin_headers, managers=("user-id",)):
    await client.post(
        "/api/v1/groups",
        headers=admin_headers,
        json={"name": "team", "category": "research-group", "managers": list(managers)},
    )


async def _add_member(client, headers, user_id="bob-id", group="team"):
    return await client.post(
        f"/api/v1/groups/{group}/members", headers=headers, json={"userId": user_id}
    )


async def test_non_manager_cannot_revoke_or_edit_membership(
    client, admin_headers, bob_headers
):
    await _setup_team(client, admin_headers)
    mid = (await _add_member(client, admin_headers)).json()["id"]

    assert (await client.delete(f"/api/v1/memberships/{mid}", headers=bob_headers)).status_code == 403
    patched = await client.patch(
        f"/api/v1/memberships/{mid}", headers=bob_headers, json={"expiresAt": None}
    )
    assert patched.status_code == 403


async def test_manager_can_manage_own_group_members(client, admin_headers, user_headers):
    await _setup_team(client, admin_headers)  # alice (user-id) manages team
    added = await _add_member(client, user_headers)
    assert added.status_code == 201
    rm = await client.delete(f"/api/v1/memberships/{added.json()['id']}", headers=user_headers)
    assert rm.status_code == 204


async def test_manager_cannot_touch_other_groups(client, admin_headers, user_headers):
    await _setup_team(client, admin_headers)
    await client.post(
        "/api/v1/groups", headers=admin_headers, json={"name": "other", "category": "other"}
    )
    mid = (await _add_member(client, admin_headers, group="other")).json()["id"]
    assert (await client.delete(f"/api/v1/memberships/{mid}", headers=user_headers)).status_code == 403
    assert (await _add_member(client, user_headers, group="other")).status_code == 403


async def test_owner_grant_is_admin_only(client, admin_headers, user_headers, ctx):
    await _setup_team(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="u.alice", accessGroups=[])
    resp = await client.post(
        "/api/v1/grants",
        headers=user_headers,
        json={"groupName": "team", "resourceType": "dataset", "resourceIds": ["ds-1"], "mode": "owner"},
    )
    assert resp.status_code == 403
    assert ctx.scicat.resources[("dataset", "ds-1")]["ownerGroup"] == "u.alice"


async def test_manager_shares_managed_groups_resources_with_any_group(
    client, admin_headers, user_headers, ctx
):
    await _setup_team(client, admin_headers)  # alice manages team, not partners
    await client.post(
        "/api/v1/groups", headers=admin_headers, json={"name": "partners", "category": "other"}
    )
    ctx.scicat.seed_resource("dataset", "mine", ownerGroup="team", accessGroups=[])
    ctx.scicat.seed_resource("dataset", "theirs", ownerGroup="u.bob", accessGroups=[])
    resp = await client.post(
        "/api/v1/grants",
        headers=user_headers,
        json={
            "groupName": "partners",
            "resourceType": "dataset",
            "resourceIds": ["mine", "theirs"],
            "mode": "access",
        },
    )
    assert resp.status_code == 207
    by_id = {i["resourceId"]: i for i in resp.json()["items"]}
    assert by_id["mine"]["ok"] is True
    assert by_id["theirs"]["ok"] is False and "forbidden" in by_id["theirs"]["error"]
    assert ctx.scicat.resources[("dataset", "mine")]["accessGroups"] == ["partners"]
    assert ctx.scicat.resources[("dataset", "theirs")]["accessGroups"] == []


async def test_owner_side_and_receiving_side_managers_may_withdraw(
    client, admin_headers, user_headers, bob_headers, ctx
):
    await _setup_team(client, admin_headers)  # alice manages the owner group
    await client.post(
        "/api/v1/groups",
        headers=admin_headers,
        json={"name": "partners", "category": "other", "managers": ["bob-id"]},
    )
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="team", accessGroups=[])
    ctx.scicat.seed_resource("dataset", "ds-2", ownerGroup="team", accessGroups=[])
    resp = await client.post(
        "/api/v1/grants",
        headers=user_headers,
        json={"groupName": "partners", "resourceType": "dataset", "resourceIds": ["ds-1", "ds-2"]},
    )
    ids = [i["grantId"] for i in resp.json()["items"]]
    assert resp.json()["items"][0]["ok"] and resp.json()["items"][1]["ok"]
    # the receiving group's manager may not share team's data, but may give it back
    denied = await client.post(
        "/api/v1/grants",
        headers=bob_headers,
        json={"groupName": "partners", "resourceType": "dataset", "resourceIds": ["ds-1"]},
    )
    assert denied.json()["items"][0]["ok"] is False
    assert (await client.delete(f"/api/v1/grants/{ids[0]}", headers=bob_headers)).status_code == 204
    assert (await client.delete(f"/api/v1/grants/{ids[1]}", headers=user_headers)).status_code == 204
    assert ctx.scicat.resources[("dataset", "ds-1")]["accessGroups"] == []
    assert ctx.scicat.resources[("dataset", "ds-2")]["accessGroups"] == []


async def test_grant_removal_requires_group_manager(
    client, admin_headers, bob_headers, ctx
):
    await _setup_team(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="orig", accessGroups=[])
    resp = await client.post(
        "/api/v1/grants",
        headers=admin_headers,
        json={"groupName": "team", "resourceType": "dataset", "resourceIds": ["ds-1"], "mode": "access"},
    )
    grant_id = resp.json()["items"][0]["grantId"]
    assert (await client.delete(f"/api/v1/grants/{grant_id}", headers=bob_headers)).status_code == 403
    assert "team" in ctx.scicat.resources[("dataset", "ds-1")]["accessGroups"]


async def test_browse_restricted_to_managed_groups_for_managers(
    client, admin_headers, user_headers, ctx
):
    await _setup_team(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "mine", datasetName="Mine", ownerGroup="team")
    ctx.scicat.seed_resource("dataset", "member", datasetName="Member", ownerGroup="u.alice")
    ctx.scicat.seed_resource("dataset", "theirs", datasetName="Theirs", ownerGroup="u.bob")
    resp = await client.get("/api/v1/resources/dataset", headers=user_headers)
    assert [i["id"] for i in resp.json()["items"]] == ["mine"]
    admin = await client.get("/api/v1/resources/dataset", headers=admin_headers)
    assert {i["id"] for i in admin.json()["items"]} == {"mine", "member", "theirs"}


async def test_plain_users_cannot_read_directory_or_admin_views(client, bob_headers):
    for path in (
        "/api/v1/users?q=a",
        "/api/v1/users/user-id/groups",
        "/api/v1/grants",
        "/api/v1/expiry",
        "/api/v1/transfer-rules",
        "/api/v1/transfer-records",
        "/api/v1/resources/dataset",
    ):
        assert (await client.get(path, headers=bob_headers)).status_code == 403, path
    # /me stays available to every authenticated user (catorga contract)
    assert (await client.get("/api/v1/me", headers=bob_headers)).status_code == 200


async def test_manager_may_only_edit_description(client, admin_headers, user_headers):
    await _setup_team(client, admin_headers)
    ok = await client.patch("/api/v1/groups/team", headers=user_headers, json={"description": "d"})
    assert ok.status_code == 200
    for body in ({"managers": ["user-id", "bob-id"]}, {"status": "retired"}, {"category": "other"}):
        resp = await client.patch("/api/v1/groups/team", headers=user_headers, json=body)
        assert resp.status_code == 403, body


async def test_unknown_token_401_and_whoami_cached(client, ctx, admin_headers):
    assert (await client.get("/api/v1/me", headers={"Authorization": "Bearer nope"})).status_code == 401
    calls = ctx.scicat.whoami_calls
    await client.get("/api/v1/groups", headers=admin_headers)
    await client.get("/api/v1/groups", headers=admin_headers)
    assert ctx.scicat.whoami_calls == calls + 1


async def test_scicat_outage_maps_to_503(client, ctx):
    from app.services.scicat_client import ScicatUnavailable

    async def down(token):
        raise ScicatUnavailable("connection refused")

    ctx.scicat.whoami = down
    resp = await client.get("/api/v1/me", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 503
