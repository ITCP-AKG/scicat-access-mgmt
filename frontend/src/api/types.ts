export type GroupCategory = 'research-group' | 'project' | 'administrative' | 'instrument' | 'other';
export type GroupStatus = 'active' | 'retired';

export interface Group {
  name: string;
  description: string;
  category: GroupCategory;
  managers: string[];
  status: GroupStatus;
  createdAt: string;
  createdBy: string;
  modifiedAt: string;
  modifiedBy: string;
}

export interface GroupDetail extends Group {
  memberCount: number;
  grantCount: number;
  transferRuleCount: number;
}

export interface GroupCreate {
  name: string;
  description?: string;
  category: GroupCategory;
  managers?: string[];
  /** Required when SciCat users already carry the name: adopt them (true) or strip it (false). */
  importHolders?: boolean | null;
}

export interface NameCheck {
  name: string;
  valid: boolean;
  reserved: boolean;
  exists: boolean;
  collidesWithUser: boolean;
  /** Users whose SciCat identity already carries this group string. */
  holders: number;
}

export type MembershipStatus = 'active' | 'scheduled' | 'expired' | 'revoked';

export interface Membership {
  id: string;
  groupName: string;
  userId: string;
  userDisplay: string;
  effectiveFrom: string | null;
  expiresAt: string | null;
  status: MembershipStatus;
  addedAt: string;
  addedBy: string;
}

export interface DirectoryUser {
  userId: string;
  username: string;
  displayName: string;
  email: string;
  accessGroups: string[];
  active: boolean;
}

export interface Me {
  userId: string;
  username: string;
  displayName?: string;
  email?: string;
  currentGroups: string[];
  isAdmin: boolean;
  managerOf: string[];
}

export type InviteStatus = 'pending' | 'accepted' | 'revoked' | 'expired';

/** A personal group invitation: single-use, bound to `email`, expiring, revocable. */
export interface Invite {
  id: string;
  groupName: string;
  email: string;
  createdBy: string;
  createdAt: string;
  expiresAt: string;
  membershipExpiresAt: string | null;
  status: InviteStatus;
  acceptedBy: string | null;
  acceptedAt: string | null;
  revokedBy: string | null;
  revokedAt: string | null;
}

export interface InviteCreate {
  groupName: string;
  email: string;
  validDays?: number;
  membershipExpiresAt?: string | null;
}

/** Returned once: the token is not stored, so the link cannot be shown again. */
export interface InviteCreated extends Invite {
  token: string;
  /** Empty when the server has no INVITE_LINK_BASE configured. */
  link: string;
}

export interface GrantDriftItem {
  grantId: string;
  groupName: string;
  resourceType: string;
  resourceId: string;
  mode: string;
  issue: string;
  fixed: boolean;
}

export interface SyncResult {
  ranAt: string;
  usersUpdated: number;
  drift: { userId: string; expected: string[]; actual: string[] }[];
  grantDrift: GrantDriftItem[];
  errors: string[];
}

// Only these SciCat v4.3.1 types carry ownerGroup/accessGroups (no instruments/jobs).
// 'project' is a catorga project: the proposal plus its samples, datasets and blocks.
export type ResourceType = 'project' | 'dataset' | 'origdatablock' | 'proposal' | 'sample';
export type GrantMode = 'owner' | 'access';
export type GrantStatus = 'active' | 'scheduled' | 'expired' | 'removed';

export interface ResourceGrant {
  id: string;
  groupName: string;
  resourceType: ResourceType;
  resourceId: string;
  mode: GrantMode;
  effectiveFrom: string | null;
  expiresAt: string | null;
  status: GrantStatus;
  previousOwnerGroup: string | null;
  preexisting: boolean;
  appliedAt: string;
  appliedBy: string;
  endedAt: string | null;
  endedBy: string | null;
  /** SciCat refused the withdrawal: still effective, retried by the scheduler. */
  pendingRemoval: boolean;
  lastError: string | null;
  /** The resource's ownerGroup when shared: its managers may withdraw the grant. */
  resourceOwnerGroup: string | null;
  /** Set on the per-record children of a project grant. */
  parentGrantId: string | null;
  /** Project grants in a listing: their open per-record children. */
  childCount: number | null;
}

export interface BulkResultItem {
  resourceId: string;
  ok: boolean;
  error: string | null;
  grantId: string | null;
}

export interface BulkResult {
  total: number;
  succeeded: number;
  failed: number;
  items: BulkResultItem[];
}

export interface ResourceSummary {
  id: string;
  label: string;
  ownerGroup: string;
  accessGroups: string[];
}

export interface ResourcePage {
  items: ResourceSummary[];
  hasMore: boolean;
}

export interface ExpiryDashboard {
  expiringSoon: Membership[];
  recentlyExpired: Membership[];
  expiringGrants: ResourceGrant[];
}

export type SuccessorType = 'user' | 'group';
export type TransferOutcome = 'transferred' | 'pending_manual' | 'failed' | 'resolved';

export interface TransferMatch {
  userId: string | null;
  category: string | null;
  groupName: string | null;
}

export interface TransferRule {
  id: string;
  name: string;
  match: TransferMatch;
  successorType: SuccessorType;
  successor: string;
  transferOwner: boolean;
  priority: number;
  enabled: boolean;
}

export type TransferRuleCreate = Omit<TransferRule, 'id'>;

export interface TransferRecord {
  id: string;
  batchId: string;
  triggerReason: 'departure' | 'expiry' | 'manual';
  fromUserId: string;
  resourceType: ResourceType;
  resourceId: string;
  previousOwnerGroup: string;
  newOwnerGroup: string;
  ruleId: string | null;
  outcome: TransferOutcome;
  error: string | null;
  notes: string[];
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  at: string;
  by: string;
}

export interface TransferBatchResult {
  batchId: string;
  records: TransferRecord[];
  errors: string[];
}

/** One departure (deactivation or lapse of the last membership) = one transfer batch. */
export interface Departure {
  id: string;
  userId: string;
  reason: 'departure' | 'expiry' | 'manual';
  groups: string[];
  at: string;
  by: string;
  needsRetry: boolean;
  lastRunAt: string | null;
}

export type ActorKind = 'user' | 'system';

export interface AuditEntry {
  id: string;
  at: string;
  actor: string;
  actorName?: string;
  actorKind: ActorKind;
  action: string;
  entityType: string;
  entityId: string;
  summary: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface AuditQuery {
  actor?: string;
  entityType?: string;
  from?: string;
  to?: string;
  skip?: number;
  limit?: number;
}
