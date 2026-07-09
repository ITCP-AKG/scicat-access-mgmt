// Resource-specific API hooks built on the typed client (T019/T025/T031 API layer).
import { api } from './client';
import type {
  AuditEntry,
  AuditQuery,
  BulkResult,
  DirectoryUser,
  ExpiryDashboard,
  GrantMode,
  Group,
  GroupDetail,
  Me,
  Membership,
  ResourceGrant,
  ResourcePage,
  ResourceType,
  SyncResult,
  TransferBatchResult,
  TransferRecord,
  TransferRule,
  TransferRuleCreate,
} from './types';

export const GroupsApi = {
  list: (q?: string) => api.get<Group[]>(`/api/v1/groups${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  get: (name: string) => api.get<GroupDetail>(`/api/v1/groups/${encodeURIComponent(name)}`),
  create: (body: { name: string; description?: string; category: string; managers?: string[] }) =>
    api.post<Group>('/api/v1/groups', body),
  update: (name: string, body: Partial<Pick<Group, 'description' | 'category' | 'managers' | 'status'>>) =>
    api.patch<Group>(`/api/v1/groups/${encodeURIComponent(name)}`, body),
  remove: (name: string, cascade = false) =>
    api.del<void>(`/api/v1/groups/${encodeURIComponent(name)}${cascade ? '?cascade=true' : ''}`),
};

export const MembersApi = {
  list: (group: string) =>
    api.get<Membership[]>(`/api/v1/groups/${encodeURIComponent(group)}/members`),
  add: (group: string, body: { userId: string; effectiveFrom?: string | null; expiresAt?: string | null }) =>
    api.post<Membership>(`/api/v1/groups/${encodeURIComponent(group)}/members`, body),
  revoke: (id: string) => api.del<void>(`/api/v1/memberships/${id}`),
};

export const UsersApi = {
  me: () => api.get<Me>('/api/v1/me'),
  search: (q: string) => api.get<DirectoryUser[]>(`/api/v1/users?q=${encodeURIComponent(q)}`),
  groups: (userId: string) =>
    api.get<Membership[]>(`/api/v1/users/${encodeURIComponent(userId)}/groups`),
  deactivate: (userId: string) =>
    api.post<TransferBatchResult>(`/api/v1/users/${encodeURIComponent(userId)}/deactivate`),
};

export const TransfersApi = {
  listRules: () => api.get<TransferRule[]>('/api/v1/transfer-rules'),
  createRule: (body: TransferRuleCreate) =>
    api.post<TransferRule>('/api/v1/transfer-rules', body),
  updateRule: (id: string, body: TransferRuleCreate) =>
    api.patch<TransferRule>(`/api/v1/transfer-rules/${id}`, body),
  deleteRule: (id: string) => api.del<void>(`/api/v1/transfer-rules/${id}`),
  records: (params?: { fromUserId?: string; outcome?: string }) => {
    const qs = new URLSearchParams();
    if (params?.fromUserId) qs.set('fromUserId', params.fromUserId);
    if (params?.outcome) qs.set('outcome', params.outcome);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return api.get<TransferRecord[]>(`/api/v1/transfer-records${suffix}`);
  },
};

export const GrantsApi = {
  list: (params?: { groupName?: string; resourceType?: ResourceType }) => {
    const qs = new URLSearchParams();
    if (params?.groupName) qs.set('groupName', params.groupName);
    if (params?.resourceType) qs.set('resourceType', params.resourceType);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return api.get<ResourceGrant[]>(`/api/v1/grants${suffix}`);
  },
  apply: (body: {
    groupName: string;
    resourceType: ResourceType;
    resourceIds: string[];
    mode: GrantMode;
    effectiveFrom?: string | null;
    expiresAt?: string | null;
  }) => api.post<BulkResult>('/api/v1/grants', body),
  remove: (id: string) => api.del<void>(`/api/v1/grants/${id}`),
  browse: (resourceType: ResourceType, params?: { q?: string; ownerGroup?: string; skip?: number; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.q) qs.set('q', params.q);
    if (params?.ownerGroup) qs.set('ownerGroup', params.ownerGroup);
    if (params?.skip != null) qs.set('skip', String(params.skip));
    if (params?.limit != null) qs.set('limit', String(params.limit));
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return api.get<ResourcePage>(`/api/v1/resources/${resourceType}${suffix}`);
  },
};

export const AuditApi = {
  list: (q: AuditQuery = {}) => {
    const qs = new URLSearchParams();
    if (q.actor) qs.set('actor', q.actor);
    if (q.entityType) qs.set('entityType', q.entityType);
    if (q.from) qs.set('from', q.from);
    if (q.to) qs.set('to', q.to);
    if (q.skip != null) qs.set('skip', String(q.skip));
    if (q.limit != null) qs.set('limit', String(q.limit));
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return api.get<AuditEntry[]>(`/api/v1/audit${suffix}`);
  },
};

export const ExpiryApi = {
  dashboard: (withinDays = 30) =>
    api.get<ExpiryDashboard>(`/api/v1/expiry?withinDays=${withinDays}`),
};

export const ProjectionApi = {
  run: (body: { userId?: string; groupName?: string; all?: boolean }) =>
    api.post<SyncResult>('/api/v1/projection/run', body),
  reconcile: () => api.post<SyncResult>('/api/v1/projection/reconcile'),
  status: () => api.get<SyncResult>('/api/v1/projection/status'),
};
