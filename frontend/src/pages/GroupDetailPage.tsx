import { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Paper,
  Snackbar,
  Stack,
  Typography,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import { GroupsApi, MembersApi, ProjectionApi } from '../api/endpoints';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import UserPicker from '../components/UserPicker';
import TemporalWindowField, { type TemporalWindow } from '../components/TemporalWindowField';
import type { DirectoryUser } from '../api/types';

export default function GroupDetailPage() {
  const { name = '' } = useParams();
  const { me } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const group = useQuery({ queryKey: ['group', name], queryFn: () => GroupsApi.get(name) });
  const members = useQuery({ queryKey: ['members', name], queryFn: () => MembersApi.list(name) });

  const [addOpen, setAddOpen] = useState(false);
  const [user, setUser] = useState<DirectoryUser | null>(null);
  const [window, setWindow] = useState<TemporalWindow>({ effectiveFrom: null, expiresAt: null });

  const addMut = useMutation({
    mutationFn: () =>
      MembersApi.add(name, { userId: user!.userId, effectiveFrom: window.effectiveFrom, expiresAt: window.expiresAt }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['members', name] });
      qc.invalidateQueries({ queryKey: ['group', name] });
      setAddOpen(false);
      setUser(null);
      setWindow({ effectiveFrom: null, expiresAt: null });
      setToast('Member added and projected to SciCat');
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Failed to add member'),
  });

  const revokeMut = useMutation({
    mutationFn: (id: string) => MembersApi.revoke(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['members', name] });
      setToast('Membership revoked and projected');
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Failed to revoke'),
  });

  const projectMut = useMutation({
    mutationFn: () => ProjectionApi.run({ groupName: name }),
    onSuccess: (r) => setToast(`Projection complete: ${r.usersUpdated} user(s) updated`),
  });
  const reconcileMut = useMutation({
    mutationFn: () => ProjectionApi.reconcile(),
    onSuccess: (r) => setToast(`Reconcile: ${r.drift.length} drift item(s), ${r.usersUpdated} fixed`),
  });

  const deleteMut = useMutation({
    mutationFn: (cascade: boolean) => GroupsApi.remove(name, cascade),
    onSuccess: () => navigate('/groups'),
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Failed to delete'),
  });

  const columns: GridColDef[] = [
    { field: 'userDisplay', headerName: 'User', flex: 1 },
    { field: 'userId', headerName: 'User ID', flex: 1 },
    {
      field: 'status',
      headerName: 'Status',
      width: 130,
      renderCell: (p) => <Chip size="small" label={p.value} color={p.value === 'active' ? 'success' : 'default'} />,
    },
    { field: 'expiresAt', headerName: 'Expires', width: 180, valueFormatter: (v) => (v.value ? new Date(v.value).toLocaleString() : '—') },
    {
      field: 'actions',
      headerName: '',
      width: 110,
      sortable: false,
      renderCell: (p) =>
        me?.isAdmin && (
          <Button size="small" color="error" onClick={() => revokeMut.mutate(p.row.id)}>
            Remove
          </Button>
        ),
    },
  ];

  if (group.isError) return <Alert severity="error">Group not found</Alert>;

  return (
    <Box>
      <Button onClick={() => navigate('/groups')}>← Back</Button>
      <Stack direction="row" justifyContent="space-between" alignItems="center" my={1}>
        <Box>
          <Typography variant="h5">{name}</Typography>
          <Typography color="text.secondary">{group.data?.description}</Typography>
          <Stack direction="row" spacing={1} mt={1}>
            <Chip size="small" label={group.data?.category} />
            <Chip size="small" label={`${group.data?.memberCount ?? 0} members`} />
            <Chip size="small" label={group.data?.status} />
          </Stack>
        </Box>
        {me?.isAdmin && (
          <Stack direction="row" spacing={1}>
            <Button variant="outlined" onClick={() => projectMut.mutate()} disabled={projectMut.isPending}>
              Project now
            </Button>
            <Button variant="outlined" onClick={() => reconcileMut.mutate()} disabled={reconcileMut.isPending}>
              Reconcile
            </Button>
            <Button
              variant="outlined"
              color="error"
              onClick={() => {
                if (confirm(`Delete group ${name}? Members/grants will be removed.`)) deleteMut.mutate(true);
              }}
            >
              Delete
            </Button>
          </Stack>
        )}
      </Stack>

      {error && (
        <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <Paper sx={{ p: 2 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
          <Typography variant="h6">Members</Typography>
          {me?.isAdmin && (
            <Button variant="contained" onClick={() => setAddOpen(true)}>
              Add member
            </Button>
          )}
        </Stack>
        <Divider sx={{ mb: 1 }} />
        <div style={{ height: 460, width: '100%' }}>
          <DataGrid
            rows={members.data ?? []}
            columns={columns}
            getRowId={(r) => r.id}
            loading={members.isLoading}
            disableRowSelectionOnClick
          />
        </div>
      </Paper>

      <Dialog open={addOpen} onClose={() => setAddOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Add member to {name}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            <UserPicker value={user} onChange={setUser} />
            <Typography variant="caption" color="text.secondary">
              Optional time-bounded access (for students / postdocs):
            </Typography>
            <TemporalWindowField value={window} onChange={setWindow} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddOpen(false)}>Cancel</Button>
          <Button variant="contained" disabled={!user || addMut.isPending} onClick={() => addMut.mutate()}>
            Add
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={!!toast}
        autoHideDuration={4000}
        onClose={() => setToast(null)}
        message={toast ?? ''}
      />
    </Box>
  );
}
