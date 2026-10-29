import { useState } from 'react';
import { Alert, Box, Button, Chip, Paper, Snackbar, Stack, Typography } from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import UserPicker from '../components/UserPicker';
import { UsersApi } from '../api/endpoints';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import type { DirectoryUser } from '../api/types';

// View a user's group memberships (the user-centric side of US2) + departure (US6).
export default function UserGroupsPage() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const [user, setUser] = useState<DirectoryUser | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { data: memberships = [], isLoading } = useQuery({
    queryKey: ['user-groups', user?.userId],
    queryFn: () => UsersApi.groups(user!.userId),
    enabled: !!user,
  });

  const deactivateMut = useMutation({
    mutationFn: () => UsersApi.deactivate(user!.userId),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['user-groups', user?.userId] });
      qc.invalidateQueries({ queryKey: ['transfer-records'] });
      qc.invalidateQueries({ queryKey: ['transfer-batches'] });
      setUser((u) => (u ? { ...u, active: false } : u));
      const count = (o: string) => res.records.filter((r) => r.outcome === o).length;
      setToast(
        `Deactivated: memberships ended; ${count('transferred')} resource(s) transferred, ` +
          `${count('pending_manual')} need manual handling, ${count('failed')} failed` +
          (res.errors.length ? ` (${res.errors.join('; ')})` : ''),
      );
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Failed to deactivate'),
  });

  const columns: GridColDef[] = [
    { field: 'groupName', headerName: 'Group', flex: 1 },
    {
      field: 'status',
      headerName: 'Status',
      width: 140,
      renderCell: (p) => <Chip size="small" label={p.value} color={p.value === 'active' ? 'success' : 'default'} />,
    },
    { field: 'effectiveFrom', headerName: 'From', width: 180, valueFormatter: (v) => (v.value ? new Date(v.value).toLocaleString() : '—') },
    { field: 'expiresAt', headerName: 'Expires', width: 180, valueFormatter: (v) => (v.value ? new Date(v.value).toLocaleString() : '—') },
  ];

  return (
    <Box>
      <Typography variant="h5" mb={2}>
        Users
      </Typography>
      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack spacing={1} maxWidth={480}>
          <Typography variant="subtitle2">Find a user to see their groups</Typography>
          <UserPicker value={user} onChange={setUser} />
          {user && (
            <Typography variant="body2" color="text.secondary">
              Account: {user.username || '—'} · E-mail: {user.email || '—'} · User ID: {user.userId}
            </Typography>
          )}
          {user && (
            <Stack direction="row" spacing={1} alignItems="center">
              {!user.active && <Chip size="small" color="warning" label="departed" />}
              <Typography variant="body2" color="text.secondary">
                SciCat access groups: {user.accessGroups.filter(Boolean).join(', ') || '—'}
              </Typography>
            </Stack>
          )}
          {user && me?.isAdmin && (
            <Button
              variant="outlined"
              color="error"
              sx={{ alignSelf: 'flex-start' }}
              disabled={deactivateMut.isPending}
              onClick={() => {
                if (
                  confirm(
                    `Deactivate ${user.displayName || user.userId}? This ends all their group memberships ` +
                      '(removing that access in SciCat) and hands their personally owned resources to the ' +
                      'matching transfer rule. Their SciCat login itself must be disabled in the identity provider.',
                  )
                )
                  deactivateMut.mutate();
              }}
            >
              Deactivate & transfer
            </Button>
          )}
        </Stack>
      </Paper>
      {error && (
        <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {user && (
        <div style={{ height: 460, width: '100%' }}>
          <DataGrid
            rows={memberships}
            columns={columns}
            getRowId={(r) => r.id}
            loading={isLoading}
            disableRowSelectionOnClick
          />
        </div>
      )}
      <Snackbar open={!!toast} autoHideDuration={5000} onClose={() => setToast(null)} message={toast ?? ''} />
    </Box>
  );
}
