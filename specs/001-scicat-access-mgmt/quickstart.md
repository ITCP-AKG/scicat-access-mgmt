# Quickstart & Validation Guide: SciCat Access Management

This guide proves the feature end-to-end against the running dev stack. It references [data-model.md](./data-model.md) and [contracts/openapi.yaml](./contracts/openapi.yaml) rather than restating them; implementation belongs in tasks.md.

## Prerequisites

- The existing dev stack is up (`../dev-environment/docker-compose.yaml`): Traefik on `:80`, MongoDB on `:27017` (DBs `dacat` for SciCat, `scicat_access_mgmt` for this app), SciCat backend reachable at `http://scicat-backend:3000/api/v3` (host: `http://localhost:80/api/v3`).
- A SciCat admin login (the app authenticates against SciCat). Obtain a JWT:
  `POST http://localhost:80/api/v3/auth/login` with `{username,password}` → use `access_token` as `Authorization: Bearer …`.
- Backend env (see `backend/README.md`): `APP_MONGO_URI` + `APP_DB_NAME`, `SCICAT_MONGO_URI` + `SCICAT_DB_NAME=dacat` (the database is taken from `*_DB_NAME`, not the URI), `SCICAT_BASE_URL`, **`SCICAT_SERVICE_USERNAME`/`SCICAT_SERVICE_PASSWORD`** (an admin functional account — required for grants, browsing and transfers), `PERSONAL_GROUP_TEMPLATE="{username}"` (catorga's personal owner group), optional `JWT_SECRET`, scheduler intervals.

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
cd frontend && npm run typecheck && npm run lint
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
2. Confirm in SciCat: `GET /api/v3/auth/whoami` with the **user's existing token** now lists `catalysis-team-alpha` in `currentGroups` (SciCat re-reads the identity per request; no re-login needed).
3. Log the user in again (SciCat rewrites `accessGroups` at login): within ~15 s the login watcher restores the group; `GET /api/v1/me` with the new token restores it immediately.
4. Revoke the membership → group removed from `accessGroups`; strings the app does not manage (`globalaccess`, roles, static values) **preserved**.
5. `POST /projection/reconcile` → `SyncResult.drift` / `grantDrift` list any mismatch; a second run shows none.

**Expected**: SciCat access reflects app state within one on-demand run; intrinsic groups never clobbered.

### V4 — Resource grants, bulk (US4, FR-008/009/010, SC-006)
1. `GET /resources/dataset?limit=50` → `{items, hasMore}` with `ownerGroup`/`accessGroups`; `skip=50` returns the next page (dataset pids contain `/`).
2. `POST /grants {groupName:"catalysis-team-alpha", resourceType:"dataset", resourceIds:[…≥2…], mode:"access"}` → **207** `BulkResult` with per-item `ok`.
3. Verify in SciCat each dataset's `accessGroups` now contains the group (`GET /api/v3/datasets/{url-encoded pid}`).
4. `POST /grants … mode:"owner"` on one dataset → its `ownerGroup` set; `previousOwnerGroup` captured. `DELETE` it → the previous owner is restored.
5. `DELETE /grants/<id>` of an access grant → group withdrawn; entries present before the grant stay. If SciCat refuses, the answer is **202** with `pendingRemoval: true` and the sweep retries.
6. As a non-admin manager: `mode:"owner"` → 403; access grants succeed only on resources owned by the caller's groups (others fail per item as forbidden).

**Expected**: bulk apply reports per-item results, isolates failures; grants only undo what they did.

### V5 — Temporal access (US5, FR-014–017, SC-003)
1. `POST /groups/<g>/members {userId, expiresAt:<1 min ago>}` → status `expired` (or flips on next sweep).
2. `POST /groups/<g>/members {userId2, effectiveFrom:<future>}` → status `scheduled`; `GET /users/<id2>/groups` shows it inactive; projection does **not** grant it.
3. Wait for / trigger the scheduler expiry sweep → expired membership withdrawn from SciCat `accessGroups`; future one still inactive.
4. `GET /expiry?withinDays=30` → expiring-soon and recently-expired lists populated.

**Expected**: only currently-active memberships confer access; dashboard accurate.

### V6 — Ownership transfer (US6, FR-018–021, SC-004)
1. `POST /transfer-rules {name:"postdoc-handover", match:{groupName:"catalysis-team-alpha"}, successorType:"group", successor:"catalysis-team-alpha", enabled:true}` → 201.
2. Ensure `<dep>` personally owns ≥1 resource (a dataset with `ownerGroup` = their username, or `contactEmail` = their email) and also has data owned by a shared group.
3. `POST /users/<dep>/deactivate` → 202 `TransferBatchResult`; their memberships are ended (group gone from their SciCat identity); personal resources show `outcome:transferred`; shared-group data is untouched.
4. `POST /transfer-batches/<batchId>/retry` → nothing re-applied; failed/pending records are re-evaluated in place.
5. With no matching rule for another user → records `outcome:pending_manual`; add a rule and retry the batch → transferred.
6. Expiry: a member whose only membership lapses gets a departure with `reason:expiry`, matched against the lapsed group.

**Expected**: personally owned resources reassigned or flagged; shared data untouched; retry-safe.

### V7 — Audit (US7, FR-022/023/024, SC-005)
1. After V1–V6, `GET /audit?entityType=group` and `?actor=<id>` and `?from&to` → filtered entries.
2. Confirm scheduled actions (expiry/transfer) appear with `actorKind:system`.

**Expected**: every state change retrievable with actor/target/time; manual vs system distinguishable.

### V8 — AuthZ guards (FR-025/026)
1. Call any mutating endpoint (including `PATCH/DELETE /memberships/{id}` and `DELETE /grants/{id}`) with a **non-admin, non-manager** token → 403; directory and admin views → 403; `/me` → 200.
2. Admin groups (`ADMIN_GROUPS`) are reserved names, so the app can never remove administrative access (lockout impossible by construction).
3. Stop SciCat → API answers 503 (not 401).

## Definition of done for validation

All of V1–V8 pass against the dev stack, `pytest` and `npm run typecheck && npm run lint` are green, and `SyncResult` shows zero unexplained drift after a reconcile.
