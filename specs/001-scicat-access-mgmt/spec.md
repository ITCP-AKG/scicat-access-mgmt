# Feature Specification: SciCat Access Management

**Feature Branch**: `001-scicat-access-mgmt`

**Created**: 2026-06-26

**Status**: Draft

**Input**: User description: "Web interface to manage access groups for the users of a catalysis metadata organizer running on SciCat v4. Create/manage groups; add a group to the access lists for datasets, orig datablocks, users, proposals, jobs, instruments and samples; add/delete users (discoverable via a directory) to/from a group. Account for a university catalysis lab with many research groups, projects, proposals and instruments, and temporary positions (students/postdocs) so that access expiration and automatic ownership transfer are supported."

## Context & Problem Statement

SciCat v4 has no first-class concept of an access "group". A user's group membership exists only as a string array (`accessGroups`) stored on the user's identity record, normally populated by the external auth provider at login. There is no SciCat API to list groups, create groups, list users, or change a user's membership; the identity record is read-only over the REST API. Every governed resource (dataset, orig datablock, proposal, job, instrument, sample, user) carries an `ownerGroup` (single string) and `accessGroups` (string list) that the authorization engine compares against the caller's effective groups.

A university catalysis lab needs to administer this in a structured way: many research groups, projects, proposals and instruments, plus temporary staff (students, postdocs) whose access must expire and whose owned resources must be handed over when they leave. This feature delivers a dedicated administrative web application that becomes the **source of truth** for groups and membership, **projects** effective memberships back into SciCat's identity records, stamps groups onto SciCat resources, and adds the temporal access and ownership-transfer capabilities SciCat lacks.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Create and manage groups (Priority: P1)

A lab administrator opens the app, sees the catalogue of existing access groups, and creates a new group for a research team (e.g. "catalysis-team-alpha") with a description, category, and one or more responsible managers. They can later rename the description, change managers, or retire (delete) a group that is no longer used.

**Why this priority**: Without first-class, persisted groups nothing else can be managed. This is the foundational registry SciCat does not provide, and on its own it already delivers value by giving the lab a single, documented inventory of access groups.

**Independent Test**: Create a group, see it listed, edit its details, and delete it — verifiable end to end with no other story implemented. Confirm the new group name is rejected if it collides with a SciCat special group or an existing group.

**Acceptance Scenarios**:

1. **Given** an authenticated administrator, **When** they create a group with a unique name, description and category, **Then** the group appears in the group list with the creator and timestamp recorded.
2. **Given** an existing group, **When** the administrator edits its description or managers, **Then** the changes are saved and reflected in the group detail view and the audit log.
3. **Given** a proposed group name that equals a reserved/special group (e.g. `admin`, `globalaccess`, `all`, an ingestor role) or an already-existing group, **When** the administrator tries to save, **Then** the system rejects it with a clear explanation.
4. **Given** a group that is still applied to resources or has active members, **When** the administrator attempts to delete it, **Then** the system warns about the impact and requires explicit confirmation before proceeding.

---

### User Story 2 - Manage group membership (Priority: P1)

An administrator opens a group, searches the user directory for a person, and adds them as a member. They can view all members of a group and all groups a given user belongs to, and remove a member when needed.

**Why this priority**: Membership is the core act of access administration and is the capability SciCat most conspicuously lacks (the identity record cannot be edited via its API). Combined with Story 1 it forms the minimum viable product.

**Independent Test**: Search for a directory user, add them to a group, confirm they appear in the group's member list and that the group appears in that user's group list, then remove them — fully testable on its own.

**Acceptance Scenarios**:

1. **Given** a group and a directory user not yet a member, **When** the administrator adds the user, **Then** the user appears as an active member and the change is audited.
2. **Given** a group with members, **When** the administrator opens the group, **Then** all current members are listed with their membership status (active / scheduled / expired).
3. **Given** a user, **When** the administrator views that user, **Then** every group the user belongs to is listed.
4. **Given** a member of a group, **When** the administrator removes them, **Then** the user's effective membership ends and the change is audited.

---

### User Story 3 - Project effective membership into SciCat (Priority: P1)

After membership changes, the system computes each affected user's effective access groups (from their active, non-expired memberships) and writes them into SciCat's identity records so that SciCat authorization immediately reflects the administrator's intent. The administrator can also trigger a full reconciliation on demand and see its result.

**Why this priority**: Without projection, group and membership management has no effect on actual SciCat access — this is what makes the tool real rather than a private bookkeeping app. It is part of the MVP because Stories 1–2 are inert without it.

**Independent Test**: Change a membership, run projection, and verify the target user's effective access groups in SciCat now match the app's computed set; remove the membership, reconcile, and verify it is withdrawn.

**Acceptance Scenarios**:

1. **Given** a user newly added to a group, **When** projection runs, **Then** the group appears in that user's effective access groups as seen by SciCat.
2. **Given** a user whose membership was removed or has expired, **When** projection/reconciliation runs, **Then** the group is no longer present in that user's effective access groups.
3. **Given** a discrepancy between the app's intended state and SciCat's stored state, **When** the administrator runs a full reconciliation, **Then** the system reports what it changed and the two states match afterward.
4. **Given** a projection attempt that cannot complete (target unreachable), **When** the error occurs, **Then** the administrator is informed and the intended state is preserved for retry without data loss.

---

### User Story 4 - Apply a group to resource access lists (Priority: P2)

An administrator selects a group and applies it as `ownerGroup` and/or an `accessGroups` entry to one or more SciCat resources of a chosen type (datasets, orig datablocks, proposals, jobs, instruments, samples, users), individually or in bulk via multi-select.

**Why this priority**: This is how groups gain meaning over actual data. It depends on groups existing (Story 1) but is valuable independently of temporal features.

**Independent Test**: Pick a group and a set of datasets, apply the group to their access list, and verify the resources now grant that group access; remove the grant and verify it is withdrawn.

**Acceptance Scenarios**:

1. **Given** a group and a selection of resources of one type, **When** the administrator applies the group to the access list, **Then** each selected resource grants access to that group.
2. **Given** a bulk selection, **When** the operation runs, **Then** the administrator sees per-item success/failure and a summary, with partial failures not blocking the rest.
3. **Given** a resource with a group grant, **When** the administrator removes the grant, **Then** the resource no longer grants access to that group.
4. **Given** an attempt to set an `ownerGroup`, **When** applied, **Then** exactly one owner group is recorded for each resource and the prior owner is captured in the audit/transfer history.

---

### User Story 5 - Time-bounded (temporal) access (Priority: P2)

When adding a member to a group or applying a group grant to resources, the administrator can set an effective-from and/or expires-at date (e.g. matching a student's contract). The system automatically activates and revokes access as those windows open and lapse, and surfaces a dashboard of upcoming and recently-lapsed expirations with advance warnings.

**Why this priority**: Temporal access is a primary motivation for the lab (temporary positions) but builds on membership (Stories 2–3) and grants (Story 4) already existing.

**Independent Test**: Create a membership expiring in the near past and one in the near future, run the scheduler, and verify the past one is revoked while the future one is not yet active; confirm both appear correctly on the expiry dashboard.

**Acceptance Scenarios**:

1. **Given** a membership with an expires-at in the past, **When** the scheduler runs, **Then** the membership becomes inactive and the user's effective access is recomputed and projected.
2. **Given** a membership with an effective-from in the future, **When** the scheduler runs before that date, **Then** the membership is not yet active and confers no access.
3. **Given** memberships approaching expiry within the warning window, **When** the administrator opens the expiry dashboard, **Then** those memberships are listed as "expiring soon" with their dates.
4. **Given** a membership without an expires-at, **When** time passes, **Then** it remains active indefinitely (no unintended revocation).

---

### User Story 6 - Automatic ownership transfer on departure (Priority: P3)

The administrator configures transfer rules so that when a user is deactivated or their membership expires (e.g. a postdoc leaves), the resources they own and the roles they held are automatically reassigned to a designated successor user or group. Every transfer is recorded with before/after owners.

**Why this priority**: The most complex, fully-custom capability; depends on temporal access and projection already working. High value for governance but not required for the lab to begin using the tool.

**Independent Test**: Configure a rule mapping a departing user to a successor group, trigger the user's departure/expiry, and verify the user's owned resources now show the successor as owner with the transfer logged.

**Acceptance Scenarios**:

1. **Given** a transfer rule and a user whose access expires or who is deactivated, **When** the departure is processed, **Then** that user's owned resources are reassigned to the configured successor.
2. **Given** a completed transfer, **When** the administrator inspects the transfer history, **Then** each reassigned resource shows previous owner, new owner, the triggering reason, and timestamp.
3. **Given** a departure with no matching transfer rule, **When** processed, **Then** the system does not silently drop ownership; it flags the resources for manual handling and notifies the administrator.
4. **Given** a transfer that partially fails, **When** it runs, **Then** completed reassignments are kept, failures are reported, and the operation can be safely retried without double-transferring.

---

### User Story 7 - Audit and accountability (Priority: P3)

An administrator (or auditor) reviews a chronological, filterable log of every change — group create/edit/delete, membership add/remove, resource grant changes, projections, expirations, and transfers — including who performed it, when, and what changed.

**Why this priority**: Essential for governance and trust in a multi-group lab, but a cross-cutting record that depends on the other actions existing to have anything to log.

**Independent Test**: Perform a representative set of actions, open the audit view, filter by actor/entity/time, and confirm each action is recorded with actor, target, and before/after where applicable.

**Acceptance Scenarios**:

1. **Given** any state-changing action, **When** it completes, **Then** an audit entry records the actor, action, target entity, timestamp, and relevant before/after detail.
2. **Given** the audit view, **When** the administrator filters by actor, entity type, or date range, **Then** only matching entries are shown.
3. **Given** an automated action (scheduled expiry or transfer), **When** it runs, **Then** it is attributed to the system actor and is distinguishable from manual actions.

---

### Edge Cases

- A user belongs to multiple groups with overlapping or conflicting windows — effective access is the union of all currently-active memberships.
- A group is deleted while still applied to resources or referenced by a transfer rule — deletion is blocked or requires explicit cascade with warning.
- The same directory person appears under multiple identifiers — the system keys membership on a stable directory identity, not display name or email alone.
- SciCat is temporarily unreachable during projection/transfer — intended state is preserved and operations are retried; no partial corruption of the source of truth.
- An administrator removes themselves from the group that grants them administrative access — the system warns and prevents lockout of the last administrator.
- A resource's owner group is changed externally in SciCat between reads — the system detects the drift on reconciliation and reports it rather than blindly overwriting.
- Clock/timezone handling for expiry — all temporal boundaries are evaluated consistently in a single canonical timezone.
- Bulk operations over large selections — partial failures are isolated and reported per item.

## Requirements *(mandatory)*

### Functional Requirements

**Groups**

- **FR-001**: System MUST allow an authorized administrator to create, view, edit, list, and delete access groups as first-class persisted objects with at least: name (identifier), human-readable description, category/type, one or more managers, and creation/modification metadata.
- **FR-002**: System MUST enforce group name uniqueness and MUST reject names that collide with SciCat special/reserved groups (including `admin`, `globalaccess`, `all`, and ingestor/role accounts) and with the per-user implicit groups.
- **FR-003**: System MUST prevent or controllably cascade deletion of a group that still has active members, active resource grants, or transfer-rule references, warning the administrator of the impact.

**Membership & directory**

- **FR-004**: System MUST let an administrator search a user directory and add discovered users as members of a group, and remove members.
- **FR-005**: System MUST display, for any group, its current members with membership status, and for any user, the groups they belong to.
- **FR-006**: System MUST key membership on a stable directory identity so that renames or multiple contact addresses do not create duplicate or orphaned memberships.
- **FR-007**: System MUST source directory users through a replaceable provider; the initial provider reads existing SciCat users, with the design allowing an external directory (e.g. LDAP/AD) provider to be added later without reworking membership management.

**Resource grants**

- **FR-008**: System MUST allow applying a group to the owner-group and/or access-group lists of SciCat resources of these types: datasets, orig datablocks, proposals, jobs, instruments, samples, and users — both individually and as a bulk multi-select operation.
- **FR-009**: System MUST allow removing a previously applied group grant from resources.
- **FR-010**: System MUST report per-item outcomes for bulk operations and continue past individual failures, presenting a summary.

**Projection / synchronization**

- **FR-011**: System MUST compute each user's effective access groups as the union of their currently-active (within window, not expired) memberships.
- **FR-012**: System MUST project the computed effective access groups into SciCat's identity records so SciCat authorization reflects the app's state, both automatically after relevant changes and on administrator-triggered full reconciliation.
- **FR-013**: System MUST detect and report drift between its intended state and SciCat's stored state during reconciliation, and MUST NOT lose the intended (source-of-truth) state if projection fails.

**Temporal access**

- **FR-014**: System MUST allow each membership and each resource grant to carry an optional effective-from and/or expires-at boundary.
- **FR-015**: System MUST automatically activate access when an effective-from is reached and revoke access (and re-project) when an expires-at lapses, via a recurring scheduled process.
- **FR-016**: System MUST provide a dashboard of upcoming expirations within a configurable warning window and recently-lapsed expirations.
- **FR-017**: System MUST treat memberships/grants without an expires-at as indefinite.

**Ownership transfer**

- **FR-018**: System MUST let an administrator define transfer rules mapping a departing/deactivated user to a successor user or group.
- **FR-019**: System MUST, when a user is deactivated or their access expires, reassign that user's owned resources and held roles to the configured successor according to the rules, and record each reassignment.
- **FR-020**: System MUST, when no transfer rule applies, avoid silently orphaning ownership — it flags affected resources for manual handling and notifies the administrator.
- **FR-021**: Transfer operations MUST be idempotent/retry-safe so partial failures can be re-run without duplicating reassignments.

**Audit**

- **FR-022**: System MUST record an immutable audit entry for every state-changing action (group, membership, grant, projection, expiry, transfer) capturing actor, action, target, timestamp, and before/after where applicable.
- **FR-023**: System MUST distinguish automated/system actions from manual administrator actions in the audit record.
- **FR-024**: System MUST let an administrator browse and filter the audit log by actor, entity type, and date range.

**Access control & UI**

- **FR-025**: System MUST require the user to authenticate with their existing SciCat credentials and MUST restrict administrative actions to SciCat administrators and designated group managers.
- **FR-026**: System MUST prevent an administrator from removing the access that grants administration, avoiding lockout of the last administrator.
- **FR-027**: System MUST provide an intuitive administrative GUI comprising at least: a groups list/detail view, a membership editor with directory search, a resource-grant assignment view with bulk select, an expiry dashboard, a transfer-rules view, and an audit view.

### Key Entities *(include if feature involves data)*

- **Group**: A named, described, categorized access group owned/managed by one or more administrators; the unit applied to users and resources. Maps to a SciCat access-group string but holds metadata SciCat does not.
- **Directory User**: A person discoverable through the directory provider, identified by a stable directory identity, with display name and contact details; the subject of membership.
- **Membership**: An association of a directory user to a group, with status and an optional temporal window (effective-from / expires-at); the basis for computing effective access.
- **Resource Grant**: An application of a group to a specific SciCat resource (typed: dataset, orig datablock, proposal, job, instrument, sample, user) as owner-group or access-group, with an optional temporal window.
- **Effective Access (projection)**: The computed set of currently-active groups per user that is written into SciCat; a derived, reconcilable view.
- **Transfer Rule**: A configured mapping from a departing/deactivated user (or a class of users) to a successor user or group, used to drive automatic ownership transfer.
- **Transfer Record**: A logged reassignment of a resource/role from a previous owner to a new owner, with reason and timestamp.
- **Audit Entry**: An immutable record of a state-changing action with actor, action, target, timestamp, and before/after detail.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An administrator can create a group and add a member to it in under 2 minutes without referring to documentation.
- **SC-002**: A membership change is reflected in SciCat's effective access for the affected user within one reconciliation cycle (target: under 1 minute for on-demand projection).
- **SC-003**: 100% of expired memberships are revoked from effective access by the next scheduled run after their expiry boundary, with no expired membership continuing to confer access.
- **SC-004**: For a departing user covered by a transfer rule, 100% of their owned resources are either reassigned to the configured successor or explicitly flagged for manual handling — none are silently orphaned.
- **SC-005**: Every state-changing action is retrievable in the audit log with actor, target, and timestamp; an auditor can locate all changes to a given group within a date range in under 1 minute.
- **SC-006**: A bulk grant operation over at least 100 resources completes with a per-item result summary and isolates failures so a single failure does not abort the batch.
- **SC-007**: No reserved/special SciCat group name can be created as a managed group (0% acceptance of reserved names).
- **SC-008**: The system never leaves SciCat and its own source-of-truth in an unrecoverable inconsistent state after a projection/transfer failure — reconciliation restores agreement in a subsequent run.

## Assumptions

- The administrative app is the authoritative source of truth for managed groups and membership; group/membership state in SciCat is treated as a projection target that the app may overwrite to match its computed effective state. Pre-existing ad-hoc access-group strings in SciCat not known to the app are reported as drift rather than deleted.
- The app writes effective access groups directly into SciCat's identity store (no external directory exists yet to manage them in); a future LDAP/AD provider would change where membership is sourced and possibly where it is written, behind the same provider abstraction.
- No LDAP/AD server is available in the current environment; the initial directory provider enumerates existing SciCat users, and "deactivation" of a user is determined by the app's own records or directory provider rather than an external HR feed.
- Authentication reuses SciCat login (JWT); authorization for app actions is derived from SciCat administrator status and app-managed group-manager assignments.
- Resource grant operations use SciCat's supported resource APIs to set owner/access groups; resource types are limited to those enumerated (datasets, orig datablocks, proposals, jobs, instruments, samples, users).
- All temporal boundaries are evaluated in a single canonical timezone configured for the deployment.
- The frontend follows the existing catorga project's UI stack and conventions for visual and interaction consistency; established IAM/access-admin UI patterns guide the layout.
- The catalysis lab operates a single SciCat instance; multi-instance federation is out of scope for v1.
- Notifications to administrators (expiry warnings, unmatched transfers) are delivered in-app; external channels (email) are out of scope for v1 unless trivially available.
