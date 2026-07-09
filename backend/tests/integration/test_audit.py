"""US7 audit view: query filters (actor, entityType, date range) and system-vs-user
attribution (T047, quickstart V7, SC-005)."""

from datetime import datetime, timezone

import pytest

from app.scheduler.jobs import SchedulerJobs

pytestmark = pytest.mark.asyncio

FAR_PAST = "2000-01-01T00:00:00+00:00"
FAR_FUTURE = "2100-01-01T00:00:00+00:00"


async def _seed_actions(client, admin_headers, ctx, clock):
    """Produce a mix of user-driven and system-driven audit entries."""
    clock.set(datetime(2026, 1, 1, tzinfo=timezone.utc))
    await client.post(
        "/api/v1/groups", headers=admin_headers, json={"name": "team", "category": "research-group"}
    )
    await client.post(
        "/api/v1/groups/team/members",
        headers=admin_headers,
        json={"userId": "user-id", "expiresAt": "2026-01-05T00:00:00+00:00"},
    )
    # advance past expiry and sweep -> a system-attributed membership.expire entry
    clock.set(datetime(2026, 1, 10, tzinfo=timezone.utc))
    await SchedulerJobs(ctx).expiry_sweep()


async def test_audit_lists_and_filters_by_entity_type(client, admin_headers, ctx, clock):
    await _seed_actions(client, admin_headers, ctx, clock)
    resp = await client.get("/api/v1/audit", headers=admin_headers, params={"entityType": "group"})
    assert resp.status_code == 200
    entries = resp.json()
    assert entries and all(e["entityType"] == "group" for e in entries)
    assert any(e["action"] == "group.create" for e in entries)


async def test_audit_distinguishes_system_from_user(client, admin_headers, ctx, clock):
    await _seed_actions(client, admin_headers, ctx, clock)

    system = (await client.get(
        "/api/v1/audit", headers=admin_headers, params={"actor": "system"}
    )).json()
    assert system and all(e["actorKind"] == "system" for e in system)
    assert any(e["action"] == "membership.expire" for e in system)

    user = (await client.get(
        "/api/v1/audit", headers=admin_headers, params={"actor": "admin-id"}
    )).json()
    assert user and all(e["actor"] == "admin-id" and e["actorKind"] == "user" for e in user)


async def test_audit_date_range_filter(client, admin_headers, ctx, clock):
    await _seed_actions(client, admin_headers, ctx, clock)
    all_after = (await client.get(
        "/api/v1/audit", headers=admin_headers, params={"from": FAR_PAST}
    )).json()
    assert len(all_after) > 0
    none_before = (await client.get(
        "/api/v1/audit", headers=admin_headers, params={"to": FAR_PAST}
    )).json()
    assert none_before == []
    none_future = (await client.get(
        "/api/v1/audit", headers=admin_headers, params={"from": FAR_FUTURE}
    )).json()
    assert none_future == []


async def test_audit_requires_admin(client, user_headers, admin_headers, ctx, clock):
    await _seed_actions(client, admin_headers, ctx, clock)
    resp = await client.get("/api/v1/audit", headers=user_headers)
    assert resp.status_code == 403
