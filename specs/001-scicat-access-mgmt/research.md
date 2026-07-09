# Phase 0 Research: SciCat Access Management

This document records the findings (from live inspection of the running SciCat v4.3.1 instance, the official docs, and the existing catorga stack) and the resulting technical decisions that resolve the plan's open questions.

## R1. How SciCat stores groups and membership

**Findings (verified on the live instance):**
- SciCat has **no first-class group entity** and no group/membership/user-list REST endpoints. `GET /api/v3/users` → 404. Only `GET /api/v3/users/{id}`, `GET /api/v3/users/{id}/userIdentity`, and `GET /api/v3/useridentities/findOne?filter=…` exist for reading users.
- A user's group membership is the array `userIdentity.profile.accessGroups` (strings). Live example: admin's profile held `["","admin","globalaccess"]`. `auth/whoami` returns the merged `currentGroups`.
- `userIdentity` is **read-only over REST** (only `/users/{id}/settings` is writable). There is no API to create groups or change membership; for non-local auth these are populated from the IdP (`/auth/ldap`, `/auth/msad`, `/auth/oidc`) at login.
- Special/reserved groups come from backend env config: `ADMIN_GROUPS=admin`, `CREATE_DATASET_GROUPS=all`, `SAMPLE_GROUPS=all`, `SAMPLE_PRIVILEGED_GROUPS=sampleingestor`, plus implicit `globalaccess` and a per-user group equal to the username. Functional accounts (`admin`, `ingestor`, `archiveManager`, `proposalIngestor`) carry roles.

**Decision**: The app is the **source of truth** for managed groups/membership and **projects** the computed effective `accessGroups` into SciCat. Because no REST write path exists, projection writes **directly to the SciCat Mongo `UserIdentity` collection**, mutating only `profile.accessGroups` (and bumping `modified`). This is the same Mongo instance the `scicat-catalysis-addon` already connects to, so it is an established, available integration point.

**Rationale**: It is the only mechanism that takes effect for local accounts with no LDAP present, it is deterministic and reconcilable, and it confines writes to a single derived field.

**Alternatives considered**:
- *Write to LDAP/IdP* — rejected for v1: no LDAP server exists in the environment (decided with user). Kept as a future provider.
- *Use only SciCat REST* — impossible: no write path for identities/membership.
- *Custom SciCat fork/plugin to expose a groups API* — rejected: heavy, couples us to backend release cycle; the Mongo-projection approach is non-invasive.

## R2. Effective-access computation & temporal model

**Decision**: A user's **effective access groups** = the set of group names from all of that user's memberships that are *currently active* — i.e. status `active` AND (`effectiveFrom` is null or ≤ now) AND (`expiresAt` is null or > now) — unioned with any always-on baseline the deployment configures. Projection writes exactly this set (replacing the app-managed portion of `profile.accessGroups`).

**Reserved-string preservation**: SciCat-intrinsic strings the app does not manage (e.g. `globalaccess`, the username group, functional-account roles, and any pre-existing access-group strings unknown to the app) are **preserved** on projection (not deleted) and surfaced as *drift* in reconciliation reports. The app only adds/removes group names it owns (tracked via the `groups` registry), so it never clobbers SciCat internals.

**Rationale**: Union-of-active is the natural CASL semantics; confining mutation to app-owned names prevents the projection from fighting SciCat's own membership logic (FR-011, FR-013, edge case "drift").

**Time handling**: All instants stored and compared in **UTC** (FR-014–017, edge case "timezone"). The scheduler evaluates windows against a single injected `now()` for testability.

## R3. Resource group fields & how grants are applied

**Findings (verified):** every governed resource carries `ownerGroup` (single string) and `accessGroups` (string array). Identifiers and patch routes per type:

| Resource | List/Count | Patch route | ID field |
|----------|-----------|-------------|----------|
| datasets | `GET /api/v3/datasets`, `/datasets/count` | `PATCH /api/v3/datasets/{pid}` | `pid` |
| origdatablocks | `GET /api/v3/origdatablocks` | `PATCH /api/v3/origdatablocks/{id}` | `id` |
| proposals | `GET /api/v3/proposals` | `PATCH /api/v3/proposals/{pid}` | `proposalId`/`pid` |
| samples | `GET /api/v3/samples` | `PATCH /api/v3/samples/{id}` | `sampleId`/`id` |
| instruments | `GET /api/v3/instruments` | `PATCH /api/v3/instruments/{id}` | `id` |
| jobs | `GET /api/v3/jobs` | `PATCH /api/v3/jobs/{id}` | `id` |
| users | identities (Mongo) | n/a (membership = projection) | `userId` |

Datasets also expose `owner`, `ownerEmail`, `instrumentGroup`. Live sample: dataset `ownerGroup="u.iepyd"`, proposal `ownerGroup="AKG"`.

**Decision**: Resource grants are applied via the **SciCat REST API** (PATCH per resource), not via Mongo, so SciCat's own validation/hooks run. The grant service reads current `ownerGroup`/`accessGroups`, applies the change (set owner, or add/remove an accessGroups entry), and PATCHes. Bulk = iterate with per-item result capture; failures isolated (FR-010, SC-006). The "users" resource type maps to membership/projection, not a PATCH.

**Rationale**: Resources have a supported REST write path (unlike identities); using it keeps us within SciCat's contract and audit. Read-modify-write on the array avoids clobbering other groups.

**Alternatives**: bulk Mongo update — rejected (bypasses SciCat validation, riskier).

## R4. Ownership transfer

**Decision**: A `TransferRule` maps a departing user (by directory identity, optionally scoped by group/category) to a **successor** (user or group). On trigger (manual departure, user deactivation, or membership expiry caught by the scheduler), the transfer service enumerates resources the user owns — primarily by `ownerGroup` equal to the user's per-user group and/or `ownerEmail`/`owner` matching the user — and reassigns `ownerGroup` (and, when successor is a user, `owner`/`ownerEmail`) to the successor, writing a `TransferRecord` per resource. Idempotency via a recorded `(resourceType,resourceId,transferBatchId)` guard so re-runs don't double-apply (FR-021, SC-008). No matching rule → resources flagged `pending_manual` and the admin is notified (FR-020, SC-004).

**Rationale**: Matches the lab's "student/postdoc leaves" need; idempotent batches make partial failures safe to retry.

**Open detail resolved**: "owned resources" are identified by querying SciCat per resource type filtered on the departing user's owner group / owner email. This is feasible with the existing list+filter endpoints.

## R5. Authentication & authorization for the app

**Decision**: The frontend authenticates the admin against **SciCat** (`POST /api/v3/auth/login`) and receives a JWT. The JWT is sent to the backend as a Bearer token. The backend validates it **by calling SciCat `GET /api/v3/auth/whoami`** with the token (authoritative, no secret sharing needed) — optionally fast-path verifying the signature with the shared `JWT_SECRET` when configured. Authorization: an action is allowed if the caller's `currentGroups` intersect the configured admin groups (`admin`) **or** the caller is a registered **manager** of the target group (app-managed). The "last admin lockout" guard (FR-026) is enforced in the membership/group services.

**Rationale**: Reuses SciCat identity (FR-025), avoids a second credential store, and `whoami` keeps us correct even if token internals change across SciCat versions.

**Alternatives**: independent app login — rejected (second credential store, drifts from SciCat identity).

## R6. Scheduler

**Decision**: **APScheduler** (AsyncIO) embedded in the FastAPI process with three jobs: (a) **expiry sweep** — deactivate lapsed memberships/grants, recompute & project affected users; (b) **periodic reconcile** — drift detection between app state and SciCat; (c) **transfer sweep** — process departures/expiries needing ownership transfer. All jobs are idempotent and take a leader lock (a Mongo lease doc in `sync_state`) so multiple replicas don't double-run. Intervals configurable (defaults: expiry 5 min, reconcile 30 min). Manual triggers exposed via API.

**Rationale**: In-process scheduler is simplest for a single-instance lab deployment and avoids extra infrastructure (no Celery/Redis). Mongo lease keeps it safe if scaled.

**Alternatives**: external cron / Celery — rejected as over-engineered for this scale.

## R7. Frontend stack

**Decision**: Mirror `catorga_frontend`: React 18.2 + Vite 5 + TypeScript 5.2 + MUI v5 + `@mui/x-data-grid` v6 + Emotion. Add **React Router** for the multi-area admin shell and **TanStack Query** for server-state/caching of the backend API. Jest + Testing Library for tests.

**Rationale**: Consistency with the existing project (shared conventions, look-and-feel, developer familiarity); DataGrid covers the list/bulk-select UX that IAM admin tools need.

**Alternatives**: Redux for server state — rejected in favor of TanStack Query (less boilerplate for request caching/invalidation). A component library other than MUI — rejected for consistency.

## R8. Deployment integration

**Decision**: Add `access-mgmt-backend` and `access-mgmt-frontend` services to `../dev-environment/docker-compose.yaml`. Backend env: app Mongo URI (`mongodb://mongodb:27017/scicat_access_mgmt`), SciCat Mongo URI (`mongodb://mongodb:27017/dacat`), `SCICAT_BASE_URL=http://scicat-backend:3000/api/v3`, `JWT_SECRET` (shared, optional fast-path), scheduler intervals, reserved-group list. Frontend env: backend base URL, SciCat base URL for login. Exposed via Traefik (distinct path prefix) or a dedicated dev port (e.g. 5174), CORS allowing the dev origins. The compose wiring is documented in quickstart.md but kept as the final integration step.

**Rationale**: Reuses the running Mongo + SciCat; no new infra. Keeps parity with how `catalysis-addon` and `catorga-frontend` are already wired.

## Resolved unknowns summary

| Unknown | Resolution |
|--------|------------|
| Where membership writes land | SciCat Mongo `UserIdentity.profile.accessGroups` (app-owned names only) |
| How resources get grants | SciCat REST PATCH per type, read-modify-write arrays |
| How "owned resources" are found for transfer | SciCat list+filter by owner group / owner email |
| App auth | SciCat JWT validated via `whoami`; admin groups + app group-managers |
| Scheduler tech | APScheduler in-process + Mongo lease lock |
| Directory source | `scicat_local` provider over SciCat identities; LDAP provider deferred behind the protocol |
| Timezone | UTC everywhere |
