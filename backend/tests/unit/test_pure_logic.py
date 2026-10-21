"""Pure-logic unit tests (T050): reserved-name validation, temporal status, and the
effective-set computation — no Mongo or SciCat needed (injected values only).

Transfer idempotency is exercised end-to-end in tests/integration/test_transfers.py
(deterministic batchId + unique (batchId, resourceType, resourceId) guard)."""

from datetime import datetime, timezone

from app.config import Settings
from app.models.membership import compute_status
from app.models.resource_grant import compute_grant_status
from app.services.projection import ProjectionService

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
PAST = datetime(2026, 1, 1, tzinfo=timezone.utc)
FUTURE = datetime(2026, 12, 1, tzinfo=timezone.utc)


# ---- Reserved-name validation ----

def test_reserved_names_cover_scicat_specials_and_admin_groups():
    s = Settings(reserved_groups=["globalaccess", "all"], admin_groups=["admin", "lab-admins"])
    assert s.is_reserved("globalaccess")
    assert s.is_reserved("GLOBALACCESS")  # case-insensitive
    assert s.is_reserved("  all  ")       # trimmed
    assert s.is_reserved("admin")         # admin groups are reserved too
    assert s.is_reserved("lab-admins")
    assert s.is_reserved("")              # empty is not a valid name
    assert not s.is_reserved("catalysis-team")


# ---- Membership temporal status ----

def test_membership_status_matrix():
    assert compute_status(None, None, NOW) == "active"
    assert compute_status(FUTURE, None, NOW) == "scheduled"
    assert compute_status(None, PAST, NOW) == "expired"
    assert compute_status(PAST, FUTURE, NOW) == "active"
    assert compute_status(None, None, NOW, ended=True) == "revoked"
    # boundary: expiry exactly at now counts as expired
    assert compute_status(None, NOW, NOW) == "expired"


def test_grant_status_matrix():
    assert compute_grant_status(None, None, NOW) == "active"
    assert compute_grant_status(FUTURE, None, NOW) == "scheduled"
    assert compute_grant_status(None, PAST, NOW) == "expired"
    assert compute_grant_status(None, None, NOW, removed=True) == "removed"


# ---- Effective-set computation (the projection invariant) ----

def _compute(current, removable, active):
    return ProjectionService.compute_target(current, set(removable), set(active))


def test_effective_set_adds_active_app_owned_groups():
    result = _compute(["u.alice"], {"team", "proposal-1"}, {"team"})
    assert "team" in result
    assert "u.alice" in result  # intrinsic preserved


def test_effective_set_removes_inactive_app_owned_but_preserves_intrinsic():
    # "proposal-1" is app-owned but no longer active -> dropped;
    # "globalaccess" is unmanaged -> preserved.
    result = _compute(["u.alice", "globalaccess", "proposal-1"], {"team", "proposal-1"}, {"team"})
    assert "proposal-1" not in result
    assert "team" in result
    assert "u.alice" in result and "globalaccess" in result


def test_effective_set_is_stable_and_deduplicated():
    result = _compute(["team", "team", "u.alice"], {"team"}, {"team"})
    assert result.count("team") == 1
    assert sorted(result) == ["team", "u.alice"]
