"""Group invitations: a manager invites by e-mail; only the invited account can accept,
once, before the invitation expires or is revoked. Accepting adds the membership and
projects it into SciCat at once."""

from datetime import timedelta

import pytest

from app.services.invites import hash_token

pytestmark = pytest.mark.asyncio


async def _setup_team(client, admin_headers, managers=("user-id",)):
    resp = await client.post(
        "/api/v1/groups",
        headers=admin_headers,
        json={"name": "team", "category": "research-group", "managers": list(managers)},
    )
    assert resp.status_code == 201, resp.text


async def _invite(client, headers, email="Bob@catorga.dev", **extra):
    return await client.post(
        "/api/v1/invites", headers=headers, json={"groupName": "team", "email": email, **extra}
    )


async def _groups_of(ctx, user_id):
    doc = await ctx.scicat_db["UserIdentity"].find_one({"userId": user_id})
    return doc["profile"]["accessGroups"]


async def test_manager_invites_and_invitee_joins(client, admin_headers, user_headers, bob_headers, ctx):
    ctx.settings.invite_link_base = "https://catorga.dev/#/invite/"
    await _setup_team(client, admin_headers)
    resp = await _invite(client, user_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    token = body["token"]
    assert body["link"] == f"https://catorga.dev/#/invite/{token}"
    assert body["email"] == "bob@catorga.dev" and body["status"] == "pending"
    # only a hash of the token is stored
    stored = await ctx.app_db.invites.find_one({"id": body["id"]})
    assert stored["tokenHash"] == hash_token(token) and token not in str(stored)

    preview = await client.get(f"/api/v1/invites/by-token/{token}")  # no login needed
    assert preview.status_code == 200
    assert preview.json()["groupName"] == "team"
    assert preview.json()["invitedBy"] == "Alice Researcher"

    accepted = await client.post(f"/api/v1/invites/by-token/{token}/accept", headers=bob_headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"groupName": "team", "alreadyMember": False}
    assert "team" in await _groups_of(ctx, "bob-id")  # projected at once
    me = await client.get("/api/v1/me", headers=bob_headers)
    assert "team" in me.json()["currentGroups"]

    member = await ctx.app_db.memberships.find_one({"groupName": "team", "userId": "bob-id"})
    assert member["addedBy"] == "user-id"  # attributed to the inviter
    actions = {e["action"] async for e in ctx.app_db.audit_log.find({"entityType": "invite"})}
    assert actions == {"invite.create", "invite.accept"}

    # used once: accepting again with the same account is a no-op
    again = await client.post(f"/api/v1/invites/by-token/{token}/accept", headers=bob_headers)
    assert again.status_code == 200 and again.json()["alreadyMember"] is True


async def test_only_the_invited_account_can_accept(client, admin_headers, user_headers, ctx):
    await _setup_team(client, admin_headers, managers=("bob-id",))
    resp = await client.post(
        "/api/v1/invites",
        headers={"Authorization": "Bearer bob-token"},
        json={"groupName": "team", "email": "someone@else.org"},
    )
    token = resp.json()["token"]
    denied = await client.post(f"/api/v1/invites/by-token/{token}/accept", headers=user_headers)
    assert denied.status_code == 403
    assert "someone@else.org" in denied.json()["detail"]
    assert "team" not in await _groups_of(ctx, "user-id")
    stored = await ctx.app_db.invites.find_one({"tokenHash": hash_token(token)})
    assert stored["status"] == "pending"


async def test_used_invitation_is_gone_for_others(client, admin_headers, user_headers, bob_headers, ctx):
    await _setup_team(client, admin_headers)
    token = (await _invite(client, user_headers)).json()["token"]
    await client.post(f"/api/v1/invites/by-token/{token}/accept", headers=bob_headers)
    # even an account with the same e-mail cannot reuse it
    ctx.scicat.identities["eve-token"] = {
        "_id": "eve-id", "username": "eve", "email": "bob@catorga.dev", "currentGroups": [],
    }
    reuse = await client.post(
        f"/api/v1/invites/by-token/{token}/accept", headers={"Authorization": "Bearer eve-token"}
    )
    assert reuse.status_code == 410


async def test_expired_and_revoked_invitations_are_gone(
    client, admin_headers, user_headers, bob_headers, ctx, clock
):
    await _setup_team(client, admin_headers)
    expiring = (await _invite(client, user_headers, validDays=1)).json()
    revoked = (await _invite(client, user_headers)).json()

    gone = await client.delete(f"/api/v1/invites/{revoked['id']}", headers=user_headers)
    assert gone.status_code == 200 and gone.json()["status"] == "revoked"
    resp = await client.post(
        f"/api/v1/invites/by-token/{revoked['token']}/accept", headers=bob_headers
    )
    assert resp.status_code == 410

    clock.set(clock() + timedelta(days=2))
    listed = await client.get("/api/v1/invites?groupName=team", headers=user_headers)
    assert {i["id"]: i["status"] for i in listed.json()} == {
        expiring["id"]: "expired", revoked["id"]: "revoked"
    }
    assert "token" not in listed.json()[0] and "tokenHash" not in listed.json()[0]
    resp = await client.post(
        f"/api/v1/invites/by-token/{expiring['token']}/accept", headers=bob_headers
    )
    assert resp.status_code == 410
    assert "team" not in await _groups_of(ctx, "bob-id")


async def test_existing_member_accepting_is_fine(client, admin_headers, user_headers, bob_headers):
    await _setup_team(client, admin_headers)
    await client.post("/api/v1/groups/team/members", headers=admin_headers, json={"userId": "bob-id"})
    token = (await _invite(client, user_headers)).json()["token"]
    resp = await client.post(f"/api/v1/invites/by-token/{token}/accept", headers=bob_headers)
    assert resp.status_code == 200 and resp.json()["alreadyMember"] is True


async def test_membership_window_is_carried_over(
    client, admin_headers, user_headers, bob_headers, ctx, clock
):
    await _setup_team(client, admin_headers)
    until = (clock() + timedelta(days=30)).isoformat()
    token = (await _invite(client, user_headers, membershipExpiresAt=until)).json()["token"]
    await client.post(f"/api/v1/invites/by-token/{token}/accept", headers=bob_headers)
    member = await ctx.app_db.memberships.find_one({"groupName": "team", "userId": "bob-id"})
    assert member["expiresAt"] is not None


async def test_only_managers_invite_and_list(client, admin_headers, user_headers, bob_headers):
    await _setup_team(client, admin_headers)
    assert (await _invite(client, bob_headers)).status_code == 403
    assert (await client.get("/api/v1/invites?groupName=team", headers=bob_headers)).status_code == 403
    invite = (await _invite(client, user_headers)).json()
    assert (await client.delete(f"/api/v1/invites/{invite['id']}", headers=bob_headers)).status_code == 403
    assert (await _invite(client, admin_headers)).status_code == 201


async def test_invalid_invitations_rejected(client, admin_headers, user_headers):
    await _setup_team(client, admin_headers)
    assert (await _invite(client, user_headers, email="not-an-email")).status_code == 422
    assert (await _invite(client, user_headers, validDays=365)).status_code == 422
    await client.patch("/api/v1/groups/team", headers=admin_headers, json={"status": "retired"})
    assert (await _invite(client, admin_headers)).status_code == 422


async def test_unknown_token_and_unauthenticated_accept(client, admin_headers, user_headers):
    await _setup_team(client, admin_headers)
    assert (await client.get("/api/v1/invites/by-token/nope")).status_code == 404
    token = (await _invite(client, user_headers)).json()["token"]
    assert (await client.post(f"/api/v1/invites/by-token/{token}/accept")).status_code == 401
