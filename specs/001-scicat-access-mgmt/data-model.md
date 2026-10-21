# Phase 1 Data Model: SciCat Access Management

App store: MongoDB database `scicat_access_mgmt`. All timestamps are UTC instants. IDs are app-generated (ObjectId or UUID string). Below, "→" denotes a reference.

## Collection: `groups`

The first-class access group SciCat lacks. The group `name` is the exact string projected into SciCat `accessGroups` / written to resource `ownerGroup`.

| Field | Type | Notes |
|-------|------|-------|
| `_id` | id | PK |
| `name` | string | **unique**; the SciCat access-group string. Validated against reserved names (R1) and the pattern `^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,63}$`. Immutable after create. |
| `description` | string | human-readable |
| `category` | string | `research-group` \| `project` \| `administrative` \| `instrument` \| `other` (legacy `proposal` is migrated to `administrative` at startup) |
| `managers` | string[] | directory userIds allowed to manage this group (besides admins); legacy entries may be usernames |
| `status` | string | `active` \| `retired` — a retired group confers no access (projection skips it) and accepts no new members or grants |
| `createdAt` / `createdBy` | datetime / string | |
| `modifiedAt` / `modifiedBy` | datetime / string | |

**Validation**:
- `name` MUST NOT equal a reserved/special group: `admin`, `globalaccess`, `all`, `ingestor`, `archivemanager`, `proposalingestor`, `sampleingestor`, or any configured `ADMIN_GROUPS`/role string; MUST NOT collide with a per-user group (equals an existing username); MUST be unique among groups (FR-002).
- Delete blocked while `memberships` (active) or `resource_grants` (active) reference it, unless explicit cascade (FR-003). Cascade withdraws the grants from SciCat; either way, affected users are re-projected while the name is still registered so it leaves every identity.
- If SciCat identities already carry the name, creation requires `importHolders` (true: adopt them as members; false: strip it from them) — otherwise they would silently lose it on their next projection.

## Collection: `memberships`

A user's membership of a group, with optional temporal window.

| Field | Type | Notes |
|-------|------|-------|
| `_id` | id | PK |
| `groupName` | string | → `groups.name` |
| `userId` | string | stable directory identity (R1: SciCat `userId`) |
| `userDisplay` | string | denormalized display name (UX only) |
| `effectiveFrom` | datetime? | null = active immediately |
| `expiresAt` | datetime? | null = indefinite |
| `status` | string | `active` \| `scheduled` \| `expired` \| `revoked` (computed/maintained) |
| `addedAt` / `addedBy` | datetime / string | |
| `endedAt` / `endedBy` | datetime / string? | set on revoke/expiry |

**Derived status** (evaluated against `now`): `scheduled` if `effectiveFrom > now`; `expired` if `expiresAt ≤ now`; `revoked` if manually ended; else `active`. **Effective** ⇔ `active`.

**Uniqueness**: at most one non-ended membership per (`groupName`,`userId`).

**Relationships**: many memberships → one group; many → one directory user.

## Collection: `resource_grants`

Application of a group to a SciCat resource's access list, optionally time-bounded.

| Field | Type | Notes |
|-------|------|-------|
| `_id` | id | PK |
| `groupName` | string | → `groups.name` |
| `resourceType` | string | `dataset` \| `origdatablock` \| `proposal` \| `sample` (instruments and jobs carry no ownerGroup/accessGroups in SciCat v4.3.1; legacy grants on them are retired by a startup migration) |
| `resourceId` | string | SciCat id (pid / `_id` / proposalId / sampleId) |
| `mode` | string | `owner` (sets `ownerGroup`) \| `access` (adds to `accessGroups`) |
| `effectiveFrom` | datetime? | |
| `expiresAt` | datetime? | |
| `status` | string | `active` \| `scheduled` \| `expired` \| `removed` |
| `previousOwnerGroup` | string? | `mode=owner`: the owner before the app took over; restored on withdrawal (only while the resource is still owned by the group) |
| `preexisting` | bool | the group already owned / had access when the grant took effect; withdrawal then leaves it in place |
| `appliedAt` / `appliedBy` | datetime / string | |
| `endedAt` / `endedBy` | datetime / string? | |
| `pendingRemoval` / `pendingStatus` / `endRequestedBy` | bool / string / string | SciCat refused the withdrawal: the grant stays effective and the sweep retries until it can move to `pendingStatus` |
| `lastError` | string? | last failure, or a note on how the grant ended (e.g. "ownerGroup already changed") |
| `supersededBy` | string? | the grant that replaced this one (same group/resource/mode) |

**Validation**: `resourceType=users` is **not** a grant — it is membership/projection (R3). At most one open `owner` grant per resource (a second group's owner grant fails until the first is removed); re-applying a grant for the same group carries over `previousOwnerGroup`/`preexisting`. Windows: `expiresAt` in the future, `effectiveFrom < expiresAt`.

## Collection: `transfer_rules`

| Field | Type | Notes |
|-------|------|-------|
| `_id` | id | PK |
| `name` | string | label |
| `match` | object | `{ userId? , category? , groupName? }` — selects departing users in scope |
| `successorType` | string | `user` \| `group` |
| `successor` | string | userId or groupName |
| `transferOwner` | bool | user successors: also hand over contact fields that name the departing user (dataset `owner`/`ownerEmail`/`contactEmail`, proposal `email`/`pi_email` + names, sample `owner`) |
| `priority` | int | lower = evaluated first |
| `enabled` | bool | |
| `createdAt`/`createdBy` etc. | | |

## Collection: `departures`

One per transfer trigger (deactivation, or lapse of a user's last membership). Its `id` is the `batchId` of the resulting records; retrying re-runs it with the current rules.

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | batch id |
| `userId` | string | departing user |
| `reason` | string | `departure` \| `expiry` \| `manual` |
| `groups` | string[] | groups the user belonged to when leaving — transfer rules match against these (their SciCat groups are already projected away) |
| `at` / `by` | datetime / string | |
| `needsRetry` | bool | SciCat could not be listed or refused a reassignment; retried by the reconcile job |
| `lastRunAt` | datetime? | |

## Collection: `departed_users`

`_id` = userId, `departedAt`, `by`. Marks a user deactivated in the app (directory shows them as departed); cleared when they are added to a group again. SciCat login is not blocked by the app.

## Collection: `transfer_records`

One per resource a departing user personally owned (audit + idempotency). A resource is the user's when its `ownerGroup` equals their personal group (`PERSONAL_GROUP_TEMPLATE`, `{username}` in catorga) or a contact field names them; shared-group data is never transferred.

| Field | Type | Notes |
|-------|------|-------|
| `_id` | id | PK |
| `batchId` | string | → `departures.id` (idempotency key with resource) |
| `triggerReason` | string | `departure` \| `expiry` \| `manual` |
| `fromUserId` | string | departing user |
| `resourceType` / `resourceId` | string | |
| `previousOwnerGroup` / `previousOwner` | string | |
| `newOwnerGroup` / `newOwner` | string | |
| `ruleId` | string? | → transfer_rules; null if unmatched |
| `outcome` | string | `transferred` \| `pending_manual` \| `failed` \| `resolved` (no longer owned by the user when retried) |
| `error` | string? | |
| `notes` | string[] | e.g. "contact fields still name the departing user" |
| `before` / `after` | object | the fields changed |
| `at` / `by` | datetime / string | `by` = `system` for scheduled |

**Idempotency**: unique on (`batchId`,`resourceType`,`resourceId`); a retry updates `failed`/`pending_manual` records in place and never re-applies `transferred` ones.

## Collection: `audit_log`

Append-only. Immutable.

| Field | Type | Notes |
|-------|------|-------|
| `_id` | id | PK |
| `at` | datetime | |
| `actor` | string | userId, or `system` for scheduled jobs (FR-023) |
| `actorName` | string | readable username at the time of the action |
| `actorKind` | string | `user` \| `system` |
| `action` | string | e.g. `group.create`, `membership.add`, `grant.apply`, `projection.run`, `membership.expire`, `transfer.execute` |
| `entityType` | string | `group` \| `membership` \| `grant` \| `transfer` \| `projection` \| `user` |
| `entityId` | string | |
| `before` / `after` | object? | relevant diff |
| `summary` | string | human-readable line |

**Query**: filterable by `actor`, `entityType`, time range (FR-024). Indexed on `at`, `actor`, `entityType`.

## Collection: `sync_state`

Operational singleton(s) for the engine.

| Field | Type | Notes |
|-------|------|-------|
| `_id` | string | `projection`, `reconcile`, `expiry-sweep`, `login-watch`, `scheduler-lease` |
| `lastRunAt` | datetime | |
| `lastResult` | object | counts, drift items, errors |
| `leaseOwner` / `leaseExpiresAt` | string / datetime | scheduler leader lock (R6) |
| `cursor` / `handled` | datetime / string[] | `login-watch`: last SciCat `UserIdentity.modified` processed, and changes already handled inside the overlap window |

## Collection: `projection_state`

`_id` = userId, `lastProjected` (string[]), `at`. The app-managed groups last written onto that user's identity. Projection may remove exactly these plus currently registered group names — so names of deleted groups are still cleaned up, while strings the app never wrote (SciCat static values, roles, IdP groups) are preserved.

## Derived / external (not stored here)

- **DirectoryUser** (from `directory` provider, read-only): `userId`, `username`, `displayName`, `email`, `accessGroups` (as currently in SciCat), `active`. Source v1 = SciCat `UserIdentity`.
- **Effective access set** per user: (current SciCat accessGroups − app-managed names) ∪ groups of the user's active memberships in active groups; written to SciCat `UserIdentity.profile.accessGroups` with a compare-and-set on the array that was read. SciCat rewrites this array on every login, so the login watcher and `GET /me` re-project.

## Entity relationships

```text
groups (1) ──< memberships >── (1) DirectoryUser           # membership join
groups (1) ──< resource_grants >── SciCat resource          # grants
transfer_rules (1) ──< transfer_records                      # transfer outcomes
* state-changing op ──> audit_log                            # cross-cutting
memberships(active) ──projection──> SciCat UserIdentity.profile.accessGroups
resource_grants(active) ──REST PATCH──> SciCat resource ownerGroup/accessGroups
```

## State transitions

**Membership**: `scheduled` → `active` (effectiveFrom reached) → `expired` (expiresAt reached) | `revoked` (manual). Any active→ended triggers re-projection of the user.

**ResourceGrant**: `scheduled` → `active` → `expired` | `removed`. active→ended triggers a SciCat PATCH to withdraw the grant.

**TransferRecord outcome**: `transferred` (success) | `pending_manual` (no rule) | `failed` (retry-safe via batchId).
