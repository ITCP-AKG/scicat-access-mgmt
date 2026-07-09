export type GroupCategory = 'research-group' | 'project' | 'proposal' | 'instrument' | 'other';
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
  currentGroups: string[];
  isAdmin: boolean;
  managerOf: string[];
}

export interface SyncResult {
  ranAt: string;
  usersUpdated: number;
  drift: { userId: string; expected: string[]; actual: string[] }[];
  errors: string[];
}

export type ResourceType =
  | 'dataset'
  | 'origdatablock'
  | 'proposal'
  | 'sample'
  | 'instrument'
  | 'job';
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
  appliedAt: string;
  appliedBy: string;
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
  total: number;
  items: ResourceSummary[];
}

export interface ExpiryDashboard {
  expiringSoon: Membership[];
  recentlyExpired: Membership[];
  expiringGrants: ResourceGrant[];
}

export type SuccessorType = 'user' | 'group';
export type TransferOutcome = 'transferred' | 'pending_manual' | 'failed';

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
  at: string;
  by: string;
}

export interface TransferBatchResult {
  batchId: string;
  records: TransferRecord[];
}

export type ActorKind = 'user' | 'system';

export interface AuditEntry {
  id: string;
  at: string;
  actor: string;
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
