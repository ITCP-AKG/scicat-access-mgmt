# Phase 1 Data Model: SciCat Access Management

App store: MongoDB database `scicat_access_mgmt`. All timestamps are UTC instants. IDs are app-generated (ObjectId or UUID string). Below, "→" denotes a reference.

## Collection: `groups`

The first-class access group SciCat lacks. The group `name` is the exact string projected into SciCat `accessGroups` / written to resource `ownerGroup`.

| Field | Type | Notes |
|-------|------|-------|
| `_id` | id | PK |
| `name` | string | **unique**; the SciCat access-group string. Validated against reserved names (R1). Immutable after create. |
| `description` | string | human-readable |
| `category` | string | enum-ish: `research-group` \| `project` \| `proposal` \| `instrument` \| `other` |
| `managers` | string[] | directory identities allowed to manage this group (besides admins) |
| `status` | string | `active` \| `retired` |
| `createdAt` / `createdBy` | datetime / string | |
| `modifiedAt` / `modifiedBy` | datetime / string | |

**Validation**:
- `name` MUST NOT equal a reserved/special group: `admin`, `globalaccess`, `all`, `ingestor`, `archivemanager`, `proposalingestor`, `sampleingestor`, or any configured `ADMIN_GROUPS`/role string; MUST NOT collide with a per-user group (equals an existing username); MUST be unique among groups (FR-002).
- Delete blocked while `memberships` (active) or `resource_grants` (active) reference it, unless explicit cascade (FR-003).

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
| `resourceType` | string | `dataset` \| `origdatablock` \| `proposal` \| `sample` \| `instrument` \| `job` |
| `resourceId` | string | SciCat id (pid / proposalId / sampleId / id) |
| `mode` | string | `owner` (sets `ownerGroup`) \| `access` (adds to `accessGroups`) |
| `effectiveFrom` | datetime? | |
| `expiresAt` | datetime? | |
| `status` | string | `active` \| `scheduled` \| `expired` \| `removed` |
| `previousOwnerGroup` | string? | captured when `mode=owner` (for audit/restore) |
| `appliedAt` / `appliedBy` | datetime / string | |

**Validation**: `resourceType=users` is **not** a grant — it is membership/projection (R3). Exactly one `owner` mode per resource is meaningful; applying `owner` records the prior owner.

## Collection: `transfer_rules`

| Field | Type | Notes |
|-------|------|-------|
| `_id` | id | PK |
| `name` | string | label |
| `match` | object | `{ userId? , category? , groupName? }` — selects departing users in scope |
| `successorType` | string | `user` \| `group` |
| `successor` | string | userId or groupName |
| `transferOwner` | bool | also reassign `owner`/`ownerEmail` when successor is a user |
| `priority` | int | lower = evaluated first |
| `enabled` | bool | |
| `createdAt`/`createdBy` etc. | | |

## Collection: `transfer_records`

One per reassigned resource (audit + idempotency).

| Field | Type | Notes |
|-------|------|-------|
| `_id` | id | PK |
| `batchId` | string | groups a transfer run (idempotency key with resource) |
| `triggerReason` | string | `departure` \| `expiry` \| `manual` |
| `fromUserId` | string | departing user |
| `resourceType` / `resourceId` | string | |
| `previousOwnerGroup` / `previousOwner` | string | |
| `newOwnerGroup` / `newOwner` | string | |
| `ruleId` | string? | → transfer_rules; null if unmatched |
| `outcome` | string | `transferred` \| `pending_manual` \| `failed` |
| `error` | string? | |
| `at` / `by` | datetime / string | `by` = `system` for scheduled |

**Idempotency**: unique on (`batchId`,`resourceType`,`resourceId`).

## Collection: `audit_log`

Append-only. Immutable.

| Field | Type | Notes |
|-------|------|-------|
| `_id` | id | PK |
| `at` | datetime | |
| `actor` | string | userId, or `system` for scheduled jobs (FR-023) |
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
| `_id` | string | e.g. `projection`, `scheduler-lease` |
| `lastRunAt` | datetime | |
| `lastResult` | object | counts, drift items, errors |
| `leaseOwner` / `leaseExpiresAt` | string / datetime | scheduler leader lock (R6) |

## Derived / external (not stored here)

- **DirectoryUser** (from `directory` provider, read-only): `userId`, `username`, `displayName`, `email`, `accessGroups` (as currently in SciCat), `active`. Source v1 = SciCat `UserIdentity`.
- **Effective access set** per user: computed from `memberships` (active) ∪ preserved SciCat-intrinsic strings; written to SciCat `UserIdentity.profile.accessGroups`. Not persisted in the app store except as `sync_state.lastResult` snapshots.

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
