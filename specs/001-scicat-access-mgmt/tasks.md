---
description: "Task list for SciCat Access Management implementation"
---

# Tasks: SciCat Access Management

**Input**: Design documents from `specs/001-scicat-access-mgmt/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/openapi.yaml, quickstart.md

**Tests**: Targeted contract + integration tests are included per story because the plan specifies a pytest/Jest stack and quickstart.md defines V1–V8 validation scenarios. They are not exhaustive TDD; write the listed tests before/alongside the story's implementation.

**Organization**: Tasks are grouped by user story. The three P1 stories (US1 Groups → US2 Membership → US3 Projection) form the MVP.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1–US7 maps to the user stories in spec.md

## Path Conventions

Web app: `backend/app/...`, `backend/tests/...`, `frontend/src/...`, `frontend/tests/...` (per plan.md Structure Decision).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Scaffold the backend and frontend projects.

- [X] T001 Create the repo structure per plan.md: `backend/app/{auth,models,services,services/directory,scheduler,api}/` and `frontend/src/{api,auth,components,pages}/`, each with `__init__.py`/index placeholders.
- [X] T002 Initialize the backend Python project in `backend/pyproject.toml` with FastAPI, Uvicorn, Pydantic v2, Motor, httpx, APScheduler, PyJWT, pytest, pytest-asyncio, mongomock-motor; add `backend/Dockerfile`.
- [X] T003 [P] Initialize the frontend project in `frontend/package.json` (React 18.2, Vite 5, TypeScript 5.2, MUI v5, `@mui/x-data-grid` v6, `@emotion/*`, react-router-dom, `@tanstack/react-query`, jest + testing-library) plus `frontend/{vite.config.ts,tsconfig.json,index.html}` and `frontend/Dockerfile`.
- [X] T004 [P] Configure backend linting/formatting (ruff + black config in `backend/pyproject.toml`) and frontend eslint/prettier (`frontend/.eslintrc.cjs`, `frontend/.prettierrc`) mirroring catorga_frontend conventions.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure all user stories depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 Implement settings in `backend/app/config.py` (app Mongo URI, SciCat Mongo URI `dacat`, `SCICAT_BASE_URL`, optional `JWT_SECRET`, scheduler intervals, `RESERVED_GROUPS` defaulting to admin/globalaccess/all/ingestor/archivemanager/proposalingestor/sampleingestor, warning window, canonical TZ=UTC).
- [X] T006 Implement Motor clients in `backend/app/db.py`: app DB (`scicat_access_mgmt`) and SciCat DB (`dacat`); index creation for collections in data-model.md (unique `groups.name`, membership `(groupName,userId)` partial unique, audit indexes on `at/actor/entityType`, transfer_records unique `(batchId,resourceType,resourceId)`).
- [X] T007 [P] Implement the SciCat REST client in `backend/app/services/scicat_client.py` (httpx): `whoami(token)`, `list_resources(type, query, skip, limit)`, `get_resource(type, id)`, `patch_resource(type, id, body)`, `count(type)`; per-type id/route map from research.md R3.
- [X] T008 [P] Implement JWT validation in `backend/app/auth/jwt.py` (verify via SciCat `whoami`, optional local `JWT_SECRET` fast-path) and FastAPI deps in `backend/app/auth/deps.py`: `current_user`, `require_admin`, `require_group_manager(group)` using configured admin groups + app group managers.
- [X] T009 [P] Implement the audit writer + query in `backend/app/services/audit.py` and model `backend/app/models/audit.py` (append-only writes; `actorKind` user/system). Audit is foundational because every story writes to it; the audit *view* is US7.
- [X] T010 [P] Implement the directory provider protocol in `backend/app/services/directory/base.py` (`search`, `get`, `list`, `is_active`) and the `scicat_local` provider in `backend/app/services/directory/scicat_local.py` reading SciCat `UserIdentity` (Mongo) → `DirectoryUser`; model in `backend/app/models/directory.py`.
- [X] T011 Implement the FastAPI app factory + router mount in `backend/app/main.py` and `backend/app/api/router.py` (mount all routers under `/api/v1`, CORS for dev origins, health endpoint) and the `GET /api/v1/me` endpoint in `backend/app/api/users.py` (returns identity, currentGroups, isAdmin, managerOf).
- [X] T012 [P] Set up the frontend app shell in `frontend/src/{main.tsx,App.tsx}`: MUI theme, React Query client, React Router with an authenticated layout + nav for the 7 areas.
- [X] T013 [P] Implement frontend auth in `frontend/src/auth/` (SciCat login form → `POST /api/v3/auth/login`, token storage, `useMe()` from `/api/v1/me`, route guard) and the typed backend API client base in `frontend/src/api/client.ts`.
- [X] T014 [P] Add backend test harness in `backend/tests/conftest.py` (ephemeral/mongomock Mongo, fake SciCat client, injectable `now()` clock, admin/non-admin token fixtures).

**Checkpoint**: Foundation ready — user stories can begin.

---

## Phase 3: User Story 1 - Create and manage groups (Priority: P1) 🎯 MVP

**Goal**: First-class group registry with create/edit/list/delete and reserved-name + reference guards.

**Independent Test**: Create a group, list it, edit it, attempt reserved/duplicate names (rejected), delete with/without references — per quickstart V1.

### Tests for User Story 1

- [X] T015 [P] [US1] Contract/integration test for groups CRUD + reserved-name 409 + delete-guard 409 in `backend/tests/integration/test_groups.py` (covers quickstart V1).

### Implementation for User Story 1

- [X] T016 [P] [US1] Create the Group model in `backend/app/models/group.py` (fields + `GroupCreate`/`GroupUpdate`/`GroupDetail` per data-model.md & openapi.yaml).
- [X] T017 [US1] Implement `backend/app/services/groups.py`: create/list/get/update/delete with reserved-name validation, uniqueness, per-user-group collision check, and delete-reference guard (active memberships/grants); writes audit entries.
- [X] T018 [US1] Implement the groups router in `backend/app/api/groups.py` (`GET/POST /groups`, `GET/PATCH/DELETE /groups/{name}` incl. `?cascade`) wired to admin/manager auth.
- [X] T019 [P] [US1] Build the frontend Groups list + create/edit in `frontend/src/pages/GroupsPage.tsx` (DataGrid, create/edit dialog, reserved-name error surfacing) and API hooks in `frontend/src/api/groups.ts`.
- [X] T020 [P] [US1] Build the Group detail shell in `frontend/src/pages/GroupDetailPage.tsx` (header, category/managers, retire/delete with impact warning); member/grant panels added in US2/US4.

**Checkpoint**: Groups manageable end-to-end (quickstart V1 passes).

---

## Phase 4: User Story 2 - Manage group membership (Priority: P1)

**Goal**: Add/remove directory users to/from groups; view a group's members and a user's groups.

**Independent Test**: Search a directory user, add to a group, see them in the group and the group on the user, remove — per quickstart V2.

### Tests for User Story 2

- [X] T021 [P] [US2] Integration test for membership add/list/remove + user→groups + last-admin lockout 422 in `backend/tests/integration/test_memberships.py` (covers quickstart V2 & V8).

### Implementation for User Story 2

- [X] T022 [P] [US2] Create the Membership model in `backend/app/models/membership.py` (fields + derived-status logic + `MembershipCreate`/`MembershipUpdate`).
- [X] T023 [US2] Implement `backend/app/services/memberships.py`: add/list/update/revoke, status computation against injected clock, one-active-per-(group,user) guard, last-admin lockout guard (FR-026); audit on each change.
- [X] T024 [US2] Implement routers: membership endpoints in `backend/app/api/memberships.py` (`GET/POST /groups/{name}/members`, `PATCH/DELETE /memberships/{id}`) and directory endpoints in `backend/app/api/users.py` (`GET /users` search, `GET /users/{userId}/groups`).
- [X] T025 [P] [US2] Build the membership editor `frontend/src/pages/MembershipEditor.tsx` + a reusable `frontend/src/components/UserPicker.tsx` (directory search) + `frontend/src/components/TemporalWindowField.tsx` (used now without dates; dates activated in US5); embed members panel into GroupDetailPage.
- [X] T026 [P] [US2] Build a user-centric view in `frontend/src/pages/UserGroupsPage.tsx` (a user's groups) with API hooks in `frontend/src/api/users.ts`.

**Checkpoint**: Membership manageable; US1+US2 work independently (quickstart V2 passes).

---

## Phase 5: User Story 3 - Project effective membership into SciCat (Priority: P1)

**Goal**: Compute each user's effective access groups and write them into SciCat `UserIdentity.profile.accessGroups`; on-demand projection + reconciliation with drift reporting.

**Independent Test**: Add member → project → verify group appears in SciCat identity; revoke → reconcile → group removed, intrinsic strings preserved — per quickstart V3.

### Tests for User Story 3

- [X] T027 [P] [US3] Integration test for projection (add→project→present, revoke→project→absent), intrinsic-string preservation, and reconcile drift report in `backend/tests/integration/test_projection.py` (covers quickstart V3).

### Implementation for User Story 3

- [X] T028 [US3] Implement `backend/app/services/projection.py`: compute effective set = active memberships ∪ preserved SciCat-intrinsic/unmanaged strings; write `profile.accessGroups` to SciCat `UserIdentity` (Mongo) only for app-owned names; bump `modified`; record `sync_state`; audit `projection.run`. Preserve-vs-manage logic keyed on the `groups` registry (research.md R2).
- [X] T029 [US3] Implement `backend/app/services/reconcile.py`: diff intended vs actual across users, return drift list, apply fixes; safe on SciCat-unreachable (preserve intended state). Trigger projection automatically from membership changes (hook into T023).
- [X] T030 [US3] Implement the projection router in `backend/app/api/projection.py` (`POST /projection/run`, `POST /projection/reconcile`, `GET /projection/status`).
- [X] T031 [P] [US3] Add a frontend sync/status panel (e.g. in `frontend/src/pages/GroupDetailPage.tsx` or a `SyncStatus` component) with "Project now" / "Reconcile" actions and drift display; API hooks in `frontend/src/api/projection.ts`.

**Checkpoint**: 🎯 **MVP complete** — groups + membership + real effect on SciCat access (quickstart V1–V3 pass).

---

## Phase 6: User Story 4 - Apply a group to resource access lists (Priority: P2)

**Goal**: Apply/remove a group as ownerGroup/accessGroups on datasets, origdatablocks, proposals, samples, instruments, jobs — individually and in bulk.

**Independent Test**: Select a group + datasets, apply to access list, verify in SciCat; remove — per quickstart V4.

### Tests for User Story 4

- [X] T032 [P] [US4] Integration test for bulk grant apply (207 per-item results, partial-failure isolation), owner-mode previousOwnerGroup capture, and grant removal in `backend/tests/integration/test_grants.py` (covers quickstart V4 & SC-006).

### Implementation for User Story 4

- [X] T033 [P] [US4] Create the ResourceGrant model in `backend/app/models/resource_grant.py` (+ `GrantApply`, `BulkResult`, `ResourcePage` per openapi.yaml).
- [X] T034 [US4] Implement `backend/app/services/grants.py`: read-modify-write `ownerGroup`/`accessGroups` via scicat_client per resource, bulk iterate with per-item results, capture previous owner, remove-grant withdrawal; persist grants; audit each.
- [X] T035 [US4] Implement the grants router in `backend/app/api/grants.py` (`GET/POST /grants`, `DELETE /grants/{id}`, `GET /resources/{resourceType}` browse proxy).
- [X] T036 [P] [US4] Build `frontend/src/pages/ResourceGrantsPage.tsx`: resource-type selector, browsable DataGrid with multi-select, "apply group" dialog (owner/access mode), per-item result summary; API hooks in `frontend/src/api/grants.ts` (implemented in `frontend/src/api/endpoints.ts` per existing layout).

**Checkpoint**: Groups can be applied to SciCat resources in bulk (quickstart V4 passes).

---

## Phase 7: User Story 5 - Time-bounded (temporal) access (Priority: P2)

**Goal**: effective-from/expires-at on memberships and grants; scheduler activates/revokes and re-projects; expiry dashboard with warnings.

**Independent Test**: Past-expiry and future-start memberships behave correctly after a sweep; dashboard lists them — per quickstart V5.

### Tests for User Story 5

- [X] T037 [P] [US5] Integration test (injected clock) for expiry sweep deactivating lapsed + activating reached windows + re-projection, and `/expiry` dashboard contents in `backend/tests/integration/test_temporal.py` (covers quickstart V5 & SC-003).

### Implementation for User Story 5

- [X] T038 [US5] Extend membership & grant services (T023, T034) to honor `effectiveFrom`/`expiresAt` in status computation and effective-set filtering; ensure projection (T028) only counts active windows. (Added `sweep()` to both services materialising transitions; projection already filters to active windows. tz-aware Mongo clients keep UTC comparisons safe.)
- [X] T039 [US5] Implement the scheduler in `backend/app/scheduler/jobs.py` (APScheduler asyncio): expiry sweep + periodic reconcile, Mongo lease leader-lock in `sync_state`, attributed to `system` actor; start/stop in `backend/app/main.py`.
- [X] T040 [US5] Implement the expiry router in `backend/app/api/expiry.py` (`GET /expiry?withinDays`) returning expiringSoon/recentlyExpired/expiringGrants.
- [X] T041 [P] [US5] Build `frontend/src/pages/ExpiryDashboard.tsx` (expiring-soon / recently-expired / expiring-grants tables) and enable date inputs in `TemporalWindowField` across membership & grant dialogs; API hooks in `frontend/src/api/expiry.ts` (implemented in `frontend/src/api/endpoints.ts`).

**Checkpoint**: Temporal access enforced automatically with a dashboard (quickstart V5 passes).

---

## Phase 8: User Story 6 - Automatic ownership transfer (Priority: P3)

**Goal**: Transfer rules reassign a departing/expired user's owned resources to a successor; idempotent batches; unmatched flagged for manual handling; all logged.

**Independent Test**: Configure a rule, deactivate a user owning a resource, verify reassignment + records; re-run is idempotent; unmatched → pending_manual — per quickstart V6.

### Tests for User Story 6

- [X] T042 [P] [US6] Integration test for transfer rule match → reassignment, idempotent re-run (batchId guard), and no-rule → pending_manual in `backend/tests/integration/test_transfers.py` (covers quickstart V6 & SC-004).

### Implementation for User Story 6

- [X] T043 [P] [US6] Create TransferRule + TransferRecord models in `backend/app/models/transfer.py` (per data-model.md & openapi.yaml).
- [X] T044 [US6] Implement `backend/app/services/transfers.py`: rule matching by priority; enumerate owned resources via scicat_client (filter by user group / ownerEmail); reassign ownerGroup (+owner/ownerEmail when successor is a user); write idempotent TransferRecords; flag pending_manual + notify when unmatched; audit.
- [X] T045 [US6] Wire transfer triggers: `POST /users/{userId}/deactivate` in `backend/app/api/users.py`, expiry-driven transfers in the scheduler sweep (T039), and transfer-rules/records routes in `backend/app/api/transfers.py`. (Also extended the group delete-guard to count transfer-rule references per FR-003.)
- [X] T046 [P] [US6] Build `frontend/src/pages/TransferRulesPage.tsx` (rule CRUD, transfer-records/history view, pending-manual alerts) + a deactivate action on the user view; API hooks in `frontend/src/api/transfers.ts` (implemented in `frontend/src/api/endpoints.ts`).

**Checkpoint**: Departures trigger logged, retry-safe ownership transfer (quickstart V6 passes).

---

## Phase 9: User Story 7 - Audit and accountability (Priority: P3)

**Goal**: Browsable, filterable audit log distinguishing manual vs system actions. (Audit *writing* is foundational T009; this delivers the *view*.)

**Independent Test**: After actions, filter audit by actor/entity/time; system actions distinguishable — per quickstart V7.

### Tests for User Story 7

- [X] T047 [P] [US7] Integration test for audit query filters (actor, entityType, date range) and system-vs-user attribution in `backend/tests/integration/test_audit.py` (covers quickstart V7 & SC-005).

### Implementation for User Story 7

- [X] T048 [US7] Implement the audit router in `backend/app/api/audit.py` (`GET /audit` with actor/entityType/from/to/skip/limit filters) over the audit service (T009).
- [X] T049 [P] [US7] Build `frontend/src/pages/AuditPage.tsx` (filterable DataGrid: actor, entity type, date range; before/after detail; system vs user badge) with API hooks in `frontend/src/api/audit.ts` (implemented in `frontend/src/api/endpoints.ts`).

**Checkpoint**: Full accountability view (quickstart V7 passes).

---

## Phase 10: Polish & Cross-Cutting Concerns

- [X] T050 [P] Add backend unit tests in `backend/tests/unit/` for reserved-name validation, effective-set computation, and (status/grant) temporal logic — pure logic, no Mongo/SciCat. (Transfer idempotency is covered end-to-end in `tests/integration/test_transfers.py`.) → `backend/tests/unit/test_pure_logic.py`.
- [ ] T051 [P] Add frontend tests in `frontend/tests/` for GroupsPage, MembershipEditor, and ResourceGrantsPage (Testing Library). (`npm run lint` / `tsc --noEmit` are clean.)
- [X] T052 Add `access-mgmt-backend` and `access-mgmt-frontend` services to **both** `../dev-environment/docker-compose.yaml` (live reload, ports 3100/5174) and `../deployment/docker-compose.yaml` (Traefik under `/access-mgmt` with a StripPrefix middleware). Dockerfiles added under each `dockerfiles/`; `deployment/.env.example` extended with `ACCESS_MGMT_*`.
- [X] T053 [P] Write `backend/README.md` and `frontend/README.md` (run/test/env). Added an in-app HTML user manual at `frontend/public/manual.html` (linked as "User Manual" in the nav).
- [ ] T054 Run the full quickstart.md V1–V8 against the live dev stack; confirm `pytest` and `npm test && npm run lint` are green and reconcile shows zero unexplained drift. (Requires a running docker stack — not executed here.)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup; **blocks all user stories**.
- **US1 (Phase 3)**: after Foundational.
- **US2 (Phase 4)**: after US1 (memberships reference groups; delete-guard in US1 reads memberships).
- **US3 (Phase 5)**: after US2 (projects from memberships) → completes MVP.
- **US4 (Phase 6)**: after Foundational + US1 (grants reference groups); independent of US2/US3.
- **US5 (Phase 7)**: after US2, US3, US4 (extends membership/grant/projection with windows + scheduler).
- **US6 (Phase 8)**: after US5 (uses scheduler + expiry triggers) and US4 (resource patching).
- **US7 (Phase 9)**: after Foundational (audit writes exist); view can land anytime after Phase 2 but is most useful last.
- **Polish (Phase 10)**: after the desired stories.

### Within Each User Story

- Tests → Models → Services → Endpoints → Frontend.
- Models before services; services before endpoints; backend before its frontend page.

### Parallel Opportunities

- Setup: T003, T004 parallel to T002.
- Foundational: T007, T008, T009, T010, T012, T013, T014 are largely parallel after T005/T006.
- Within a story, `[P]` model + frontend tasks run alongside backend service work on different files.
- With multiple developers after Foundational: US1→US2→US3 chain on one track; US4 in parallel on another; US7 view in parallel anytime.

---

## Parallel Example: User Story 1

```bash
# After T015 (test) is in place, parallelizable US1 tasks on different files:
Task: "T016 Create the Group model in backend/app/models/group.py"
Task: "T019 Build Groups list/create/edit in frontend/src/pages/GroupsPage.tsx"
Task: "T020 Build Group detail shell in frontend/src/pages/GroupDetailPage.tsx"
# T017 (service) then T018 (router) run after T016.
```

---

## Implementation Strategy

### MVP First (US1 + US2 + US3 — the P1 trio)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. US1 Groups → 4. US2 Membership → 5. US3 Projection.
6. **STOP and VALIDATE**: quickstart V1–V3 against the live SciCat — group membership now actually governs SciCat access.

### Incremental Delivery

- MVP (US1–US3) → demo.
- + US4 resource grants → demo.
- + US5 temporal/scheduler → demo.
- + US6 transfer → demo.
- + US7 audit view → demo.
- Phase 10 polish + docker-compose wiring + full quickstart.

---

## Notes

- `[P]` = different files, no dependency on incomplete tasks.
- Audit writing is foundational (T009); every state-changing service must emit an audit entry — the US7 phase only adds the query/view.
- Projection mutates only app-owned group names in SciCat `UserIdentity`; intrinsic strings are preserved (research.md R2) — keep this invariant under test (T027).
- All temporal logic uses an injected clock for deterministic tests.
- Commit after each task or logical group; stop at any checkpoint to validate a story independently.
