"""US6 ownership transfer: rule match → reassignment, idempotent re-run (batch guard),
and no-rule → pending_manual (T042, quickstart V6, SC-004)."""

import pytest

pytestmark = pytest.mark.asyncio


async def _make_group(client, headers, name):
    await client.post(
        "/api/v1/groups", headers=headers, json={"name": name, "category": "research-group"}
    )


async def _make_rule(client, headers, **overrides):
    body = {
        "name": "postdoc-handover",
        "match": {"userId": "user-id"},
        "successorType": "group",
        "successor": "successor-team",
        "transferOwner": False,
        "priority": 10,
        "enabled": True,
    }
    body.update(overrides)
    return await client.post("/api/v1/transfer-rules", headers=headers, json=body)


async def test_deactivate_transfers_owned_resources(client, admin_headers, ctx):
    await _make_group(client, admin_headers, "successor-team")
    await _make_rule(client, admin_headers)
    # alice (user-id) owns ds-1 via her personal group u.alice
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="u.alice", owner="alice")

    resp = await client.post("/api/v1/users/user-id/deactivate", headers=admin_headers)
    assert resp.status_code == 202
    body = resp.json()
    assert len(body["records"]) == 1
    rec = body["records"][0]
    assert rec["outcome"] == "transferred"
    assert rec["previousOwnerGroup"] == "u.alice"
    assert rec["newOwnerGroup"] == "successor-team"
    assert ctx.scicat.resources[("dataset", "ds-1")]["ownerGroup"] == "successor-team"

    # the departure is recorded in the app (SciCat's identity is left alone)
    assert await ctx.app_db.departed_users.find_one({"_id": "user-id"})
    users = (await client.get("/api/v1/users?q=alice", headers=admin_headers)).json()
    assert users[0]["active"] is False


async def test_redeactivate_is_idempotent(client, admin_headers, ctx):
    await _make_group(client, admin_headers, "successor-team")
    await _make_rule(client, admin_headers)
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="u.alice")

    first = await client.post("/api/v1/users/user-id/deactivate", headers=admin_headers)
    assert len(first.json()["records"]) == 1
    # second run: resource already moved + batch guard => no new records
    second = await client.post("/api/v1/users/user-id/deactivate", headers=admin_headers)
    assert second.json()["records"] == []

    records = (
        await client.get("/api/v1/transfer-records?fromUserId=user-id", headers=admin_headers)
    ).json()
    assert len(records) == 1


async def test_no_matching_rule_flags_pending_manual(client, admin_headers, ctx):
    # rule matches a different user; alice has no rule
    await _make_group(client, admin_headers, "successor-team")
    await _make_rule(client, admin_headers, match={"userId": "someone-else"})
    ctx.scicat.seed_resource("dataset", "ds-1", ownerGroup="u.alice")

    resp = await client.post("/api/v1/users/user-id/deactivate", headers=admin_headers)
    body = resp.json()
    assert len(body["records"]) == 1
    assert body["records"][0]["outcome"] == "pending_manual"
    # ownership untouched — never silently orphaned
    assert ctx.scicat.resources[("dataset", "ds-1")]["ownerGroup"] == "u.alice"


async def test_transfer_owner_to_user_successor(client, admin_headers, ctx):
    await _make_rule(
        client, admin_headers,
        successorType="user", successor="bob-id", transferOwner=True,
    )
    ctx.scicat.seed_resource(
        "dataset", "ds-1", ownerGroup="u.alice", owner="alice",
        ownerEmail="Alice@catorga.dev", contactEmail="pi@catorga.dev",
    )

    resp = await client.post("/api/v1/users/user-id/deactivate", headers=admin_headers)
    rec = resp.json()["records"][0]
    assert rec["outcome"] == "transferred"
    res = ctx.scicat.resources[("dataset", "ds-1")]
    assert res["ownerGroup"] == "u.bob"
    assert res["owner"] == "bob"
    assert res["ownerEmail"] == "bob@catorga.dev"  # matched case-insensitively
    assert res["contactEmail"] == "pi@catorga.dev"  # names someone else: untouched


async def test_rule_crud_and_records_require_auth(client, admin_headers, user_headers):
    # non-admin cannot create a rule
    forbidden = await _make_rule(client, user_headers)
    assert forbidden.status_code == 403

    created = await _make_rule(client, admin_headers)
    assert created.status_code == 201
    rule_id = created.json()["id"]

    listed = await client.get("/api/v1/transfer-rules", headers=admin_headers)
    assert any(r["id"] == rule_id for r in listed.json())

    deleted = await client.delete(f"/api/v1/transfer-rules/{rule_id}", headers=admin_headers)
    assert deleted.status_code == 204


async def test_group_delete_blocked_by_transfer_rule_reference(client, admin_headers):
    await _make_group(client, admin_headers, "successor-team")
    await _make_rule(client, admin_headers, successorType="group", successor="successor-team")
    resp = await client.delete("/api/v1/groups/successor-team", headers=admin_headers)
    assert resp.status_code == 409
