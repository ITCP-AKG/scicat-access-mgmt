# Quickstart & Validation Guide: SciCat Access Management

This guide proves the feature end-to-end against the running dev stack. It references [data-model.md](./data-model.md) and [contracts/openapi.yaml](./contracts/openapi.yaml) rather than restating them; implementation belongs in tasks.md.

## Prerequisites

- The existing dev stack is up (`../dev-environment/docker-compose.yaml`): Traefik on `:80`, MongoDB on `:27017` (DBs `dacat` for SciCat, `scicat_access_mgmt` for this app), SciCat backend reachable at `http://scicat-backend:3000/api/v3` (host: `http://localhost:80/api/v3`).
- A SciCat admin login (the app authenticates against SciCat). Obtain a JWT:
  `POST http://localhost:80/api/v3/auth/login` with `{username,password}` → use `access_token` as `Authorization: Bearer …`.
- Backend env (see research.md R8): `APP_MONGO_URI`, `SCICAT_MONGO_URI=mongodb://mongodb:27017/dacat`, `SCICAT_BASE_URL`, `JWT_SECRET` (optional fast-path), `RESERVED_GROUPS`, scheduler intervals.

## Run

Backend:
```bash
cd backend
pip install -e .            # or: uv sync
uvicorn app.main:app --reload --port 3100
```
Frontend:
```bash
cd frontend
npm install
npm run dev                 # Vite dev server (e.g. :5174), proxies /api/v1 → backend
```
Tests:
```bash
cd backend && pytest
cd frontend && npm test && npm run lint
```
(Or bring both up via the added docker-compose services — final integration task.)

## Validation scenarios

Each maps to a user story / success criterion. Run against `/api/v1` with a Bearer token.

### V1 — Group CRUD + reserved-name guard (US1, FR-001/002/003, SC-007)
1. `POST /groups {name:"catalysis-team-alpha", category:"research-group", description:"…"}` → 201.
2. `GET /groups` → includes the new group with `createdBy`/`createdAt`.
3. `POST /groups {name:"admin", …}` → **409** (reserved). Repeat with `globalaccess`, `all` → 409.
4. `PATCH /groups/catalysis-team-alpha {description:"…"}` → 200; change visible; audit entry `group.update` exists.
5. `DELETE /groups/catalysis-team-alpha` while it has a member → **409** (referenced); with `?cascade=true` → 204.

**Expected**: reserved/duplicate names rejected; deletion guarded.

### V2 — Membership + a user's groups (US2, FR-004/005/006)
1. `GET /users?q=<name>` → returns directory users from SciCat identities.
2. `POST /groups/catalysis-team-alpha/members {userId:"<id>"}` → 201, status `active`.
3. `GET /groups/catalysis-team-alpha/members` → includes the user.
4. `GET /users/<id>/groups` → includes `catalysis-team-alpha`.
5. `DELETE /memberships/<id>` → 204.

**Expected**: membership visible from both sides; revoke works; all audited.

### V3 — Projection into SciCat (US3, FR-011/012/013, SC-002)
1. Add a member (V2 step 2), then `POST /projection/run {userId:"<id>"}` → 200 `SyncResult` with `usersUpdated:1`.
2. Confirm in SciCat: that user's `userIdentity.profile.accessGroups` now contains `catalysis-team-alpha` (via `GET /api/v3/users/<id>/userIdentity`, or re-login and check `whoami.currentGroups`).
3. Revoke the membership, `POST /projection/run {userId}` → group removed from `accessGroups`; SciCat-intrinsic strings (`globalaccess`, username group) **preserved**.
4. `POST /projection/reconcile` → `SyncResult.drift` lists any mismatch; second run shows none.

**Expected**: SciCat access reflects app state within one on-demand run; intrinsic groups never clobbered.

### V4 — Resource grants, bulk (US4, FR-008/009/010, SC-006)
1. `GET /resources/dataset?limit=50` → lists datasets with `ownerGroup`/`accessGroups`.
2. `POST /grants {groupName:"catalysis-team-alpha", resourceType:"dataset", resourceIds:[…≥2…], mode:"access"}` → **207** `BulkResult` with per-item `ok`.
3. Verify in SciCat each dataset's `accessGroups` now contains the group (`GET /api/v3/datasets/{pid}`).
4. `POST /grants … mode:"owner"` on one dataset → its `ownerGroup` set; `previousOwnerGroup` captured.
5. `DELETE /grants/<id>` → group withdrawn from that resource.

**Expected**: bulk apply reports per-item results, isolates failures; owner change records prior owner.

### V5 — Temporal access (US5, FR-014–017, SC-003)
1. `POST /groups/<g>/members {userId, expiresAt:<1 min ago>}` → status `expired` (or flips on next sweep).
2. `POST /groups/<g>/members {userId2, effectiveFrom:<future>}` → status `scheduled`; `GET /users/<id2>/groups` shows it inactive; projection does **not** grant it.
3. Wait for / trigger the scheduler expiry sweep → expired membership withdrawn from SciCat `accessGroups`; future one still inactive.
4. `GET /expiry?withinDays=30` → expiring-soon and recently-expired lists populated.

**Expected**: only currently-active memberships confer access; dashboard accurate.

### V6 — Ownership transfer (US6, FR-018–021, SC-004)
1. `POST /transfer-rules {name:"postdoc-handover", match:{userId:"<dep>"}, successorType:"group", successor:"catalysis-team-alpha", enabled:true}` → 201.
2. Ensure `<dep>` owns ≥1 resource (e.g. a dataset `ownerGroup` = their user group / `ownerEmail`).
3. `POST /users/<dep>/deactivate` → 202 `TransferBatchResult`; records show `outcome:transferred`, `newOwnerGroup:catalysis-team-alpha`, prior owner captured.
4. Re-run deactivate (idempotency) → no double-transfer (same `batchId` guard); already-transferred resources not re-applied.
5. With no matching rule for another user → records `outcome:pending_manual`; admin notified, nothing silently orphaned.

**Expected**: owned resources reassigned or flagged; transfers logged; retry-safe.

### V7 — Audit (US7, FR-022/023/024, SC-005)
1. After V1–V6, `GET /audit?entityType=group` and `?actor=<id>` and `?from&to` → filtered entries.
2. Confirm scheduled actions (expiry/transfer) appear with `actorKind:system`.

**Expected**: every state change retrievable with actor/target/time; manual vs system distinguishable.

### V8 — AuthZ guards (FR-025/026)
1. Call any mutating endpoint with a **non-admin, non-manager** token → 403.
2. Attempt to remove the last admin's access-granting membership → 422 (lockout prevented).

## Definition of done for validation

All of V1–V8 pass against the dev stack, `pytest` and `npm test && npm run lint` are green, and `SyncResult` shows zero unexplained drift after a reconcile.
