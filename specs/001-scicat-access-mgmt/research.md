# Phase 0 Research: SciCat Access Management

This document records the findings (from live inspection of the running SciCat v4.3.1 instance, the official docs, and the existing catorga stack) and the resulting technical decisions that resolve the plan's open questions.

## R1. How SciCat stores groups and membership

**Findings (verified on the live instance):**
- SciCat has **no first-class group entity** and no group/membership/user-list REST endpoints. `GET /api/v3/users` → 404. Only `GET /api/v3/users/{id}`, `GET /api/v3/users/{id}/userIdentity`, and `GET /api/v3/useridentities/findOne?filter=…` exist for reading users.
- A user's group membership is the array `userIdentity.profile.accessGroups` (strings). Live example: admin's profile held `["","admin","globalaccess"]`. `auth/whoami` returns the merged `currentGroups`.
- `userIdentity` is **read-only over REST** (only `/users/{id}/settings` is writable). There is no API to create groups or change membership; for non-local auth these are populated from the IdP (`/auth/ldap`, `/auth/msad`, `/auth/oidc`) at login.
- Special/reserved groups come from backend env config: `ADMIN_GROUPS=admin`, `CREATE_DATASET_GROUPS=all`, `SAMPLE_GROUPS=all`, `SAMPLE_PRIVILEGED_GROUPS=sampleingestor`, plus `globalaccess`. Functional accounts (`admin`, `ingestor`, `archiveManager`, `proposalIngestor`) carry roles. SciCat itself has no per-user group; catorga (addon + frontend) treats the bare username as a user's personal `ownerGroup`.
- **How SciCat uses `profile.accessGroups`** (verified in the backend-next v4.3.1 sources, `dist/src/auth/strategies`): `JwtStrategy.validate` re-reads the identity on **every request** and returns `currentGroups = role names ∪ profile.accessGroups` — so a projection takes effect immediately, without re-login. But the `local`, `ldap` and `oidc` strategies **overwrite** `profile.accessGroups` at every login with `AccessGroupService.getAccessGroups()` (+ role names for local). In v4.3.1 the factory is hard-wired to `AccessGroupFromStaticValuesService` (`ACCESS_GROUPS_STATIC_VALUES`, default `[""]`), so IdP group claims are not used either. Every login therefore wipes projected groups (bumping `UserIdentity.modified`).

**Decision**: The app is the **source of truth** for managed groups/membership and **projects** the computed effective `accessGroups` into SciCat. Because no REST write path exists, projection writes **directly to the SciCat Mongo `UserIdentity` collection**, mutating only `profile.accessGroups` with a compare-and-set on the array it read (never `modified`, which belongs to SciCat). To survive the login overwrite, a scheduler **login watcher** (default every 15 s) re-projects identities whose `modified` advanced, and `GET /me` re-projects the caller before answering (catorga calls it right after login). Alternative kept open: mount a custom `access-group-service-factory.js` into the SciCat container that asks this app for groups at login (couples to SciCat's compiled internals).

**Rationale**: It is the only mechanism that takes effect for local accounts with no LDAP present, it is deterministic and reconcilable, and it confines writes to a single derived field.

**Alternatives considered**:
- *Write to LDAP/IdP* — rejected for v1: no LDAP server exists in the environment (decided with user). Kept as a future provider.
- *Use only SciCat REST* — impossible: no write path for identities/membership.
- *Custom SciCat fork/plugin to expose a groups API* — rejected: heavy, couples us to backend release cycle; the Mongo-projection approach is non-invasive.

## R2. Effective-access computation & temporal model

**Decision**: A user's **effective access groups** = the set of group names from all of that user's memberships that are *currently active* — i.e. status `active` AND (`effectiveFrom` is null or ≤ now) AND (`expiresAt` is null or > now) — unioned with any always-on baseline the deployment configures. Projection writes exactly this set (replacing the app-managed portion of `profile.accessGroups`).

**Reserved-string preservation**: strings the app does not manage (static values, functional-account roles, IdP- or hand-assigned groups) are **preserved** on projection and surfaced as *drift* in reconciliation reports. The app removes only names it manages: every registered group (any status) plus whatever it last projected onto that user (`projection_state.lastProjected`), so names of deleted groups are cleaned up too. Retired groups confer no access. Creating a group whose name identities already carry requires an explicit decision (adopt the holders as members, or strip it).

**Rationale**: Union-of-active is the natural CASL semantics; confining mutation to app-owned names prevents the projection from fighting SciCat's own membership logic (FR-011, FR-013, edge case "drift").

**Time handling**: All instants stored and compared in **UTC** (FR-014–017, edge case "timezone"). The scheduler evaluates windows against a single injected `now()` for testability.

## R3. Resource group fields & how grants are applied

**Findings (verified against the backend-next v4.3.1 sources):** datasets, origdatablocks, proposals and samples carry `ownerGroup` (single string) and `accessGroups` (string array). **Instruments and jobs do not** (instrument: `pid`, `uniqueName`, `name`, `customMetadata`; v4.3.1 jobs: no ownership fields), and PATCH validation uses `forbidNonWhitelisted`, so grants on them are impossible. Identifiers and routes:

| Resource | List | Patch route | ID field |
|----------|------|-------------|----------|
| datasets | `GET /api/v3/datasets?filter=` | `PATCH /api/v3/datasets/{pid}` (URL-encode: pids contain `/`) | `pid` |
| origdatablocks | `GET /api/v3/origdatablocks?filter=` | `PATCH /api/v3/origdatablocks/{id}` | `_id` |
| proposals | `GET /api/v3/proposals?filters=` | `PATCH /api/v3/proposals/{proposalId}` | `proposalId` |
| samples | `GET /api/v3/samples?filter=` | `PATCH /api/v3/samples/{sampleId}` | `sampleId` |
| users | identities (Mongo) | n/a (membership = projection) | `userId` |

List endpoints read a JSON filter `{"where": {...}, "limits": {"limit", "skip", "order": "field:asc"}}` (note the parameter is `filters` for proposals) and return at most 100 items by default — paging must use `limits`. Contact fields accepted by PATCH: datasets `owner`, `ownerEmail`, `orcidOfOwner`, `contactEmail`; proposals `email`, `firstname`, `lastname`, `pi_email`, `pi_firstname`, `pi_lastname`; samples `owner`. catorga stores the creator's username in dataset/sample `owner` and their email in `contactEmail`.

**Decision**: Resource grants are applied via the **SciCat REST API** (PATCH per resource), not via Mongo, so SciCat's own validation/hooks run. All calls run as a configured **admin functional account** (`SCICAT_SERVICE_USERNAME/PASSWORD`, logged in lazily, re-login on 401); the app enforces its own authorization on top (owner grants admin-only; managers grant access only on resources their own groups own). The grant service reads current `ownerGroup`/`accessGroups`, applies the change, and PATCHes; it records what it changed (`previousOwnerGroup`, `preexisting`) so withdrawal only undoes the grant's own effect, and keeps a refused withdrawal pending for retry. Bulk = iterate with per-item result capture; failures isolated (FR-010, SC-006). The "users" resource type maps to membership/projection, not a PATCH.

**Rationale**: Resources have a supported REST write path (unlike identities); using it keeps us within SciCat's contract and audit. Read-modify-write on the array avoids clobbering other groups.

**Alternatives**: bulk Mongo update — rejected (bypasses SciCat validation, riskier).

## R4. Ownership transfer

**Decision**: A `TransferRule` maps a departing user (by directory identity, optionally scoped by the group/category they belonged to) to a **successor** (user or group). On trigger (deactivation, or lapse of the user's last membership caught by the scheduler) a `Departure` is recorded with the groups the user had — rules match against those, since projection has already removed them from SciCat. The transfer service enumerates (paging through all results) only resources the user **personally** owns: `ownerGroup` equal to their personal group (`PERSONAL_GROUP_TEMPLATE`, `{username}` in catorga) and/or contact fields naming them. It reassigns the personal `ownerGroup` to the successor and, for user successors with `transferOwner`, hands over the matched contact fields — one PATCH per resource, nothing else touched. Shared/project-group data is never transferred. Each departure is its own batch; retries update failed/pending records in place and never re-apply completed ones (FR-021, SC-008); batches that hit SciCat errors are retried by the reconcile job. No matching rule → resources flagged `pending_manual` (FR-020, SC-004). Deactivation also ends the user's memberships, removing their app-managed access.

**Rationale**: Matches the lab's "student/postdoc leaves" need; idempotent batches make partial failures safe to retry.

**Open detail resolved**: "owned resources" are identified by querying SciCat per resource type filtered on the departing user's owner group / owner email. This is feasible with the existing list+filter endpoints.

## R5. Authentication & authorization for the app

**Decision**: The frontend authenticates against **SciCat** (`POST /api/v3/auth/login` for functional accounts, `/auth/ldap` for university accounts) or reuses a same-origin catorga session (which may come from OIDC). The JWT is sent to the backend as a Bearer token. The backend validates it **by calling SciCat `GET /api/v3/auth/whoami`** (authoritative; cached 60 s per token) — optionally pre-checking the signature with a shared `JWT_SECRET`. A rejected token → 401; SciCat unreachable → 503. Authorization: an action is allowed if the caller's `currentGroups` intersect the configured admin groups (`admin`) **or** the caller is a registered **manager** of the target group; every mutating route checks this (all SciCat writes run as the service account, so the app is the only guard). Admin groups are reserved names and never app-managed, so the app cannot remove administrative access (FR-026).

**Rationale**: Reuses SciCat identity (FR-025), avoids a second credential store, and `whoami` keeps us correct even if token internals change across SciCat versions.

**Alternatives**: independent app login — rejected (second credential store, drifts from SciCat identity).

## R6. Scheduler

**Decision**: **APScheduler** (AsyncIO) embedded in the FastAPI process with three jobs: (a) **expiry sweep** (5 min) — materialise membership/grant windows, re-project affected users, retry refused grant withdrawals, and run ownership transfers for users whose last membership lapsed; (b) **login watcher** (15 s) — re-project identities rewritten by a SciCat login; (c) **reconcile** (30 min, and once at startup) — user and grant drift between app state and SciCat, plus retry of transfer batches that hit SciCat errors. All jobs are idempotent and take a leader lock (a Mongo lease doc in `sync_state`) so multiple replicas don't double-run. Manual triggers exposed via API.

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
| Where membership writes land | SciCat Mongo `UserIdentity.profile.accessGroups` (app-managed names only), re-applied after every SciCat login |
| How resources get grants | SciCat REST PATCH per type as an admin service account, read-modify-write arrays |
| How "owned resources" are found for transfer | SciCat list (paged via `limits`) by personal owner group / contact fields |
| App auth | SciCat JWT validated via `whoami`; admin groups + app group-managers |
| Scheduler tech | APScheduler in-process + Mongo lease lock; expiry sweep, login watcher, reconcile |
| Directory source | `scicat_local` provider over SciCat identities; LDAP provider deferred behind the protocol |
| Timezone | UTC everywhere |
