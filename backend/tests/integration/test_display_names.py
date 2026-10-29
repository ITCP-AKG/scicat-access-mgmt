"""Display-name resolution for catorga: any signed-in user may map usernames to names,
but never learns e-mails or user ids; /me carries the caller's own name and e-mail."""

import pytest

pytestmark = pytest.mark.asyncio

URL = "/api/v1/users/display-names"


async def test_plain_user_resolves_names_without_emails(client, bob_headers):
    resp = await client.post(
        URL, headers=bob_headers, json={"usernames": ["alice", "bob", "catalysis-lab", "alice"]}
    )
    assert resp.status_code == 200
    body = resp.json()
    # unknown values (real groups, functional accounts) are left out
    assert body == {"alice": "Alice Researcher", "bob": "Bob Postdoc"}
    assert "@" not in resp.text


async def test_display_name_falls_back_to_username(client, ctx, bob_headers):
    await ctx.scicat_db["UserIdentity"].insert_one(
        {"userId": "carol-id", "profile": {"id": "carol-id", "username": "carol"}}
    )
    resp = await client.post(URL, headers=bob_headers, json={"usernames": ["carol"]})
    assert resp.json() == {"carol": "carol"}


async def test_lookup_requires_token_and_is_bounded(client, bob_headers):
    assert (await client.post(URL, json={"usernames": ["alice"]})).status_code == 401
    too_many = {"usernames": [f"u{i}" for i in range(201)]}
    assert (await client.post(URL, headers=bob_headers, json=too_many)).status_code == 422
    assert (await client.post(URL, headers=bob_headers, json={"usernames": []})).json() == {}


async def test_me_includes_display_name_and_email(client, user_headers):
    body = (await client.get("/api/v1/me", headers=user_headers)).json()
    assert body["username"] == "alice"
    assert body["displayName"] == "Alice Researcher"
    assert body["email"]
