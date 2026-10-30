import { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  MenuItem,
  Paper,
  Snackbar,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import { GrantsApi, GroupsApi, InvitesApi, MembersApi, ProjectionApi } from '../api/endpoints';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import UserPicker, { UserMultiPicker } from '../components/UserPicker';
import InviteDialog from '../components/InviteDialog';
import TemporalWindowField from '../components/TemporalWindowField';
import { CATEGORIES, EMPTY_WINDOW, windowError, type TemporalWindow } from '../lib/forms';
import type {
  DirectoryUser,
  GroupCategory,
  GroupDetail,
  GroupStatus,
  Invite,
  Membership,
  ResourceGrant,
} from '../api/types';

const fmtDate = (v: { value: string | null }) => (v.value ? new Date(v.value).toLocaleString() : '—');
const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);
const OPEN = new Set(['active', 'scheduled']);

function EditGroupDialog({
  group,
  isAdmin,
  onClose,
  onSaved,
}: {
  group: GroupDetail;
  isAdmin: boolean;
  onClose: () => void;
  onSaved: (msg: string) => void;
}) {
  const qc = useQueryClient();
  const [description, setDescription] = useState(group.description);
  const [category, setCategory] = useState<GroupCategory>(group.category);
  const [managers, setManagers] = useState<string[]>(group.managers);
  const [status, setStatus] = useState<GroupStatus>(group.status);
  const [error, setError] = useState<string | null>(null);

  const saveMut = useMutation({
    mutationFn: () =>
      GroupsApi.update(
        group.name,
        isAdmin ? { description, category, managers, status } : { description },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['group', group.name] });
      qc.invalidateQueries({ queryKey: ['groups'] });
      onSaved(status !== group.status ? `Group ${status}; members re-projected` : 'Group updated');
      onClose();
    },
    onError: (e) => setError(errorText(e, 'Failed to update group')),
  });

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Edit {group.name}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} mt={1}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField
            label="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            multiline
            minRows={2}
          />
          {isAdmin && (
            <>
              <TextField
                select
                label="Category"
                value={category}
                onChange={(e) => setCategory(e.target.value as GroupCategory)}
              >
                {CATEGORIES.map((c) => (
                  <MenuItem key={c} value={c}>
                    {c}
                  </MenuItem>
                ))}
              </TextField>
              <UserMultiPicker value={managers} onChange={setManagers} />
              <TextField
                select
                label="Status"
                value={status}
                onChange={(e) => setStatus(e.target.value as GroupStatus)}
                helperText={
                  status === 'retired'
                    ? 'A retired group gives no access; memberships and grants are kept for re-activation.'
                    : undefined
                }
              >
                <MenuItem value="active">active</MenuItem>
                <MenuItem value="retired">retired</MenuItem>
              </TextField>
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={saveMut.isPending} onClick={() => saveMut.mutate()}>
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function DeleteGroupDialog({ group, onClose }: { group: GroupDetail; onClose: () => void }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [cascade, setCascade] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inUse = group.memberCount + group.grantCount + group.transferRuleCount > 0;
  const deleteMut = useMutation({
    mutationFn: () => GroupsApi.remove(group.name, cascade),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['groups'] });
      navigate('/groups');
    },
    onError: (e) => setError(errorText(e, 'Failed to delete group')),
  });
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Delete {group.name}?</DialogTitle>
      <DialogContent>
        <Stack spacing={2} mt={1}>
          {error && <Alert severity="error">{error}</Alert>}
          <Typography variant="body2">
            The group is removed from every user's SciCat access groups. This cannot be undone;
            consider retiring it instead.
          </Typography>
          {inUse && (
            <>
              <Alert severity="warning">
                Still in use: {group.memberCount} member(s), {group.grantCount} resource grant(s),{' '}
                {group.transferRuleCount} transfer rule(s).
              </Alert>
              <FormControlLabel
                control={<Checkbox checked={cascade} onChange={(e) => setCascade(e.target.checked)} />}
                label="End all memberships, withdraw all grants from SciCat and delete the rules"
              />
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          color="error"
          variant="contained"
          disabled={(inUse && !cascade) || deleteMut.isPending}
          onClick={() => deleteMut.mutate()}
        >
          Delete
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default function GroupDetailPage() {
  const { name = '' } = useParams();
  const { me } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<'add' | 'edit' | 'delete' | 'invite' | null>(null);
  const [editing, setEditing] = useState<Membership | null>(null);
  const [showEnded, setShowEnded] = useState(false);

  const isAdmin = !!me?.isAdmin;
  const canManage = isAdmin || !!me?.managerOf.includes(name);

  const group = useQuery({ queryKey: ['group', name], queryFn: () => GroupsApi.get(name) });
  const members = useQuery({
    queryKey: ['members', name],
    queryFn: () => MembersApi.list(name),
    enabled: canManage,
  });
  const grants = useQuery({
    queryKey: ['grants', name],
    queryFn: () => GrantsApi.list({ groupName: name }),
    enabled: canManage,
  });
  const invites = useQuery({
    queryKey: ['invites', name],
    queryFn: () => InvitesApi.list(name),
    enabled: canManage,
  });

  const [user, setUser] = useState<DirectoryUser | null>(null);
  const [memberWindow, setMemberWindow] = useState<TemporalWindow>(EMPTY_WINDOW);
  const [editWindow, setEditWindow] = useState<TemporalWindow>(EMPTY_WINDOW);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['members', name] });
    qc.invalidateQueries({ queryKey: ['group', name] });
    qc.invalidateQueries({ queryKey: ['grants', name] });
  };

  const addMut = useMutation({
    mutationFn: () =>
      MembersApi.add(name, {
        userId: user!.userId,
        effectiveFrom: memberWindow.effectiveFrom,
        expiresAt: memberWindow.expiresAt,
      }),
    onSuccess: (m) => {
      refresh();
      setDialog(null);
      setUser(null);
      setMemberWindow(EMPTY_WINDOW);
      setToast(m.status === 'scheduled' ? 'Member scheduled' : 'Member added and projected to SciCat');
    },
    onError: (e) => setError(errorText(e, 'Failed to add member')),
  });

  const updateMut = useMutation({
    mutationFn: () =>
      MembersApi.update(editing!.id, {
        effectiveFrom: editWindow.effectiveFrom,
        expiresAt: editWindow.expiresAt,
      }),
    onSuccess: () => {
      refresh();
      setEditing(null);
      setToast('Membership updated');
    },
    onError: (e) => setError(errorText(e, 'Failed to update membership')),
  });

  const revokeMut = useMutation({
    mutationFn: (id: string) => MembersApi.revoke(id),
    onSuccess: () => {
      refresh();
      setToast('Membership revoked and projected');
    },
    onError: (e) => setError(errorText(e, 'Failed to revoke')),
  });

  const removeGrantMut = useMutation({
    mutationFn: (id: string) => GrantsApi.remove(id),
    onSuccess: (pending) => {
      refresh();
      setToast(
        pending?.pendingRemoval
          ? `SciCat refused the withdrawal (${pending.lastError ?? 'error'}); it will be retried`
          : 'Grant withdrawn',
      );
    },
    onError: (e) => setError(errorText(e, 'Failed to remove grant')),
  });

  const revokeInviteMut = useMutation({
    mutationFn: (id: string) => InvitesApi.revoke(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['invites', name] });
      setToast('Invitation revoked');
    },
    onError: (e) => setError(errorText(e, 'Failed to revoke the invitation')),
  });

  const projectMut = useMutation({
    mutationFn: () => ProjectionApi.run({ groupName: name }),
    onSuccess: (r) =>
      setToast(`Projection complete: ${r.usersUpdated} user(s) updated${r.errors.length ? `, ${r.errors.length} error(s)` : ''}`),
  });
  const reconcileMut = useMutation({
    mutationFn: () => ProjectionApi.reconcile(),
    onSuccess: (r) =>
      setToast(
        `Reconcile: ${r.drift.length} user drift, ${r.grantDrift.length} grant drift, ${r.usersUpdated} user(s) fixed`,
      ),
  });

  const memberColumns: GridColDef<Membership>[] = [
    { field: 'userDisplay', headerName: 'User', flex: 1 },
    { field: 'userId', headerName: 'User ID', flex: 1 },
    {
      field: 'status',
      headerName: 'Status',
      width: 120,
      renderCell: (p) => <Chip size="small" label={p.value} color={p.value === 'active' ? 'success' : 'default'} />,
    },
    { field: 'effectiveFrom', headerName: 'From', width: 170, valueFormatter: fmtDate },
    { field: 'expiresAt', headerName: 'Expires', width: 170, valueFormatter: fmtDate },
    {
      field: 'actions',
      headerName: '',
      width: 170,
      sortable: false,
      renderCell: (p) =>
        canManage &&
        OPEN.has(p.row.status) && (
          <Stack direction="row" spacing={1}>
            <Button
              size="small"
              onClick={() => {
                setEditing(p.row);
                setEditWindow({ effectiveFrom: p.row.effectiveFrom, expiresAt: p.row.expiresAt });
              }}
            >
              Dates
            </Button>
            <Button size="small" color="error" onClick={() => revokeMut.mutate(p.row.id)}>
              Remove
            </Button>
          </Stack>
        ),
    },
  ];

  const grantColumns: GridColDef<ResourceGrant>[] = [
    { field: 'resourceType', headerName: 'Type', width: 120 },
    {
      field: 'resourceId',
      headerName: 'Resource',
      flex: 1.3,
      valueGetter: (p) =>
        p.row.resourceType === 'project' ? `${p.row.resourceId} (${p.row.childCount ?? 0} records)` : p.row.resourceId,
    },
    { field: 'mode', headerName: 'Mode', width: 90 },
    {
      field: 'status',
      headerName: 'Status',
      width: 150,
      renderCell: (p) => (
        <Tooltip title={p.row.lastError ?? ''}>
          <Chip
            size="small"
            label={p.row.pendingRemoval ? 'removal pending' : p.value}
            color={p.row.pendingRemoval ? 'warning' : p.value === 'active' ? 'success' : 'default'}
          />
        </Tooltip>
      ),
    },
    { field: 'expiresAt', headerName: 'Expires', width: 170, valueFormatter: fmtDate },
    {
      field: 'actions',
      headerName: '',
      width: 110,
      sortable: false,
      renderCell: (p) =>
        OPEN.has(p.row.status) &&
        (p.row.mode === 'access' ? canManage : isAdmin) && (
          <Button size="small" color="error" onClick={() => removeGrantMut.mutate(p.row.id)}>
            {p.row.pendingRemoval ? 'Retry' : 'Remove'}
          </Button>
        ),
    },
  ];

  const inviteColumns: GridColDef<Invite>[] = [
    { field: 'email', headerName: 'E-mail', flex: 1 },
    {
      field: 'status',
      headerName: 'Status',
      width: 120,
      renderCell: (p) => <Chip size="small" label={p.value} color={p.value === 'accepted' ? 'success' : 'default'} />,
    },
    { field: 'createdAt', headerName: 'Sent', width: 170, valueFormatter: fmtDate },
    { field: 'expiresAt', headerName: 'Link expires', width: 170, valueFormatter: fmtDate },
    {
      field: 'actions',
      headerName: '',
      width: 110,
      sortable: false,
      renderCell: (p) =>
        p.row.status === 'pending' && (
          <Button size="small" color="error" onClick={() => revokeInviteMut.mutate(p.row.id)}>
            Revoke
          </Button>
        ),
    },
  ];

  if (group.isError) return <Alert severity="error">Group not found</Alert>;
  const detail = group.data;
  const shownGrants = (grants.data ?? []).filter((g) => showEnded || OPEN.has(g.status));
  const editError = windowError(editWindow);
  const addError = windowError(memberWindow);

  return (
    <Box>
      <Button onClick={() => navigate('/groups')}>← Back</Button>
      <Stack direction="row" justifyContent="space-between" alignItems="center" my={1}>
        <Box>
          <Typography variant="h5">{name}</Typography>
          <Typography color="text.secondary">{detail?.description}</Typography>
          <Stack direction="row" spacing={1} mt={1}>
            <Chip size="small" label={detail?.category} />
            <Chip size="small" label={`${detail?.memberCount ?? 0} members`} />
            <Chip size="small" label={`${detail?.grantCount ?? 0} grants`} />
            <Chip size="small" label={detail?.status} color={detail?.status === 'retired' ? 'warning' : 'default'} />
          </Stack>
        </Box>
        <Stack direction="row" spacing={1}>
          {canManage && detail && (
            <Button variant="outlined" onClick={() => setDialog('edit')}>
              Edit
            </Button>
          )}
          {isAdmin && (
            <>
              <Button variant="outlined" onClick={() => projectMut.mutate()} disabled={projectMut.isPending}>
                Project now
              </Button>
              <Button variant="outlined" onClick={() => reconcileMut.mutate()} disabled={reconcileMut.isPending}>
                Reconcile
              </Button>
              <Button variant="outlined" color="error" onClick={() => setDialog('delete')} disabled={!detail}>
                Delete
              </Button>
            </>
          )}
        </Stack>
      </Stack>

      {error && (
        <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {!canManage && (
        <Alert severity="info">Only administrators and this group's managers can see its members.</Alert>
      )}

      {canManage && (
        <>
          <Paper sx={{ p: 2, mb: 2 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
              <Typography variant="h6">Members</Typography>
              <Stack direction="row" spacing={1}>
                <Button
                  variant="outlined"
                  onClick={() => setDialog('invite')}
                  disabled={detail?.status === 'retired'}
                >
                  Invite by e-mail
                </Button>
                <Button
                  variant="contained"
                  onClick={() => setDialog('add')}
                  disabled={detail?.status === 'retired'}
                >
                  Add member
                </Button>
              </Stack>
            </Stack>
            <Typography variant="caption" color="text.secondary">
              The group's managers have member access too, without being listed here.
            </Typography>
            <Divider sx={{ mb: 1 }} />
            <div style={{ height: 400, width: '100%' }}>
              <DataGrid
                rows={members.data ?? []}
                columns={memberColumns}
                getRowId={(r) => r.id}
                loading={members.isLoading}
                disableRowSelectionOnClick
              />
            </div>
          </Paper>

          <Paper sx={{ p: 2, mb: 2 }}>
            <Typography variant="h6" mb={1}>
              Invitations
            </Typography>
            <Divider sx={{ mb: 1 }} />
            <div style={{ height: 260, width: '100%' }}>
              <DataGrid
                rows={invites.data ?? []}
                columns={inviteColumns}
                getRowId={(r) => r.id}
                loading={invites.isLoading}
                disableRowSelectionOnClick
                density="compact"
              />
            </div>
          </Paper>

          <Paper sx={{ p: 2 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
              <Typography variant="h6">Resource grants</Typography>
              <FormControlLabel
                control={<Checkbox size="small" checked={showEnded} onChange={(e) => setShowEnded(e.target.checked)} />}
                label="Show ended"
              />
            </Stack>
            <Divider sx={{ mb: 1 }} />
            <div style={{ height: 320, width: '100%' }}>
              <DataGrid
                rows={shownGrants}
                columns={grantColumns}
                getRowId={(r) => r.id}
                loading={grants.isLoading}
                disableRowSelectionOnClick
                density="compact"
              />
            </div>
          </Paper>
        </>
      )}

      <Dialog open={dialog === 'add'} onClose={() => setDialog(null)} fullWidth maxWidth="sm">
        <DialogTitle>Add member to {name}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            <UserPicker value={user} onChange={setUser} />
            <Typography variant="caption" color="text.secondary">
              Optional time-bounded access (for students / postdocs):
            </Typography>
            <TemporalWindowField value={memberWindow} onChange={setMemberWindow} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialog(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!user || !!addError || addMut.isPending}
            onClick={() => addMut.mutate()}
          >
            Add
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!editing} onClose={() => setEditing(null)} fullWidth maxWidth="sm">
        <DialogTitle>Membership dates — {editing?.userDisplay || editing?.userId}</DialogTitle>
        <DialogContent>
          <Box mt={1}>
            <TemporalWindowField value={editWindow} onChange={setEditWindow} />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditing(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!!editError || updateMut.isPending}
            onClick={() => updateMut.mutate()}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      {dialog === 'edit' && detail && (
        <EditGroupDialog group={detail} isAdmin={isAdmin} onClose={() => setDialog(null)} onSaved={setToast} />
      )}
      {dialog === 'delete' && detail && <DeleteGroupDialog group={detail} onClose={() => setDialog(null)} />}
      {dialog === 'invite' && <InviteDialog groups={[name]} defaultGroup={name} onClose={() => setDialog(null)} />}

      <Snackbar open={!!toast} autoHideDuration={5000} onClose={() => setToast(null)} message={toast ?? ''} />
    </Box>
  );
}
