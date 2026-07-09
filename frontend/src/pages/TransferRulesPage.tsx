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
  FormControlLabel,
  MenuItem,
  Paper,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { TransfersApi } from '../api/endpoints';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import type { SuccessorType, TransferRuleCreate } from '../api/types';

const EMPTY: TransferRuleCreate = {
  name: '',
  match: { userId: null, category: null, groupName: null },
  successorType: 'group',
  successor: '',
  transferOwner: false,
  priority: 100,
  enabled: true,
};

const outcomeColor = (o: string) =>
  o === 'transferred' ? 'success' : o === 'pending_manual' ? 'warning' : 'error';

export default function TransferRulesPage() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<TransferRuleCreate>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  const { data: rules = [], isLoading } = useQuery({
    queryKey: ['transfer-rules'],
    queryFn: () => TransfersApi.listRules(),
  });
  const { data: records = [] } = useQuery({
    queryKey: ['transfer-records'],
    queryFn: () => TransfersApi.records(),
  });

  const pendingManual = records.filter((r) => r.outcome === 'pending_manual');

  const createMut = useMutation({
    mutationFn: () => TransfersApi.createRule(draft),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['transfer-rules'] });
      setOpen(false);
      setDraft(EMPTY);
      setError(null);
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Failed to create rule'),
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => TransfersApi.deleteRule(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['transfer-rules'] }),
  });

  const ruleColumns: GridColDef[] = [
    { field: 'priority', headerName: 'Prio', width: 80 },
    { field: 'name', headerName: 'Name', flex: 1 },
    {
      field: 'match',
      headerName: 'Matches',
      flex: 1,
      renderCell: (p) =>
        [p.value.userId, p.value.groupName, p.value.category].filter(Boolean).join(' / ') || 'any',
    },
    {
      field: 'successor',
      headerName: 'Successor',
      flex: 1,
      renderCell: (p) => `${p.row.successorType}: ${p.value}`,
    },
    {
      field: 'enabled',
      headerName: 'Enabled',
      width: 110,
      renderCell: (p) => <Chip size="small" label={p.value ? 'on' : 'off'} color={p.value ? 'success' : 'default'} />,
    },
    {
      field: 'actions',
      headerName: '',
      width: 100,
      sortable: false,
      renderCell: (p) =>
        me?.isAdmin && (
          <Button size="small" color="error" onClick={() => deleteMut.mutate(p.row.id)}>
            Delete
          </Button>
        ),
    },
  ];

  const recordColumns: GridColDef[] = [
    { field: 'at', headerName: 'When', width: 180, valueFormatter: (v) => new Date(v.value).toLocaleString() },
    { field: 'fromUserId', headerName: 'From user', flex: 1 },
    { field: 'resourceType', headerName: 'Type', width: 120 },
    { field: 'resourceId', headerName: 'Resource', flex: 1 },
    { field: 'newOwnerGroup', headerName: 'New owner', flex: 1 },
    {
      field: 'outcome',
      headerName: 'Outcome',
      width: 150,
      renderCell: (p) => <Chip size="small" label={p.value} color={outcomeColor(p.value)} />,
    },
  ];

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h5">Transfer Rules</Typography>
        {me?.isAdmin && (
          <Button variant="contained" onClick={() => setOpen(true)}>
            New rule
          </Button>
        )}
      </Stack>

      {pendingManual.length > 0 && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {pendingManual.length} resource(s) need manual ownership handling (no matching rule).
        </Alert>
      )}

      <Paper sx={{ p: 2, mb: 2 }}>
        <Typography variant="h6" mb={1}>
          Rules
        </Typography>
        <div style={{ height: 320, width: '100%' }}>
          <DataGrid rows={rules} columns={ruleColumns} getRowId={(r) => r.id} loading={isLoading} disableRowSelectionOnClick density="compact" />
        </div>
      </Paper>

      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" mb={1}>
          Transfer history
        </Typography>
        <div style={{ height: 360, width: '100%' }}>
          <DataGrid rows={records} columns={recordColumns} getRowId={(r) => r.id} disableRowSelectionOnClick density="compact" />
        </div>
      </Paper>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Create transfer rule</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField label="Name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            <Typography variant="subtitle2">Match (leave blank for any)</Typography>
            <Stack direction="row" spacing={2}>
              <TextField
                label="User ID"
                value={draft.match.userId ?? ''}
                onChange={(e) => setDraft({ ...draft, match: { ...draft.match, userId: e.target.value || null } })}
              />
              <TextField
                label="Group"
                value={draft.match.groupName ?? ''}
                onChange={(e) => setDraft({ ...draft, match: { ...draft.match, groupName: e.target.value || null } })}
              />
              <TextField
                label="Category"
                value={draft.match.category ?? ''}
                onChange={(e) => setDraft({ ...draft, match: { ...draft.match, category: e.target.value || null } })}
              />
            </Stack>
            <Stack direction="row" spacing={2}>
              <TextField
                select
                label="Successor type"
                value={draft.successorType}
                onChange={(e) => setDraft({ ...draft, successorType: e.target.value as SuccessorType })}
                sx={{ width: 160 }}
              >
                <MenuItem value="group">group</MenuItem>
                <MenuItem value="user">user</MenuItem>
              </TextField>
              <TextField
                label="Successor"
                value={draft.successor}
                onChange={(e) => setDraft({ ...draft, successor: e.target.value })}
                sx={{ flexGrow: 1 }}
              />
            </Stack>
            <Stack direction="row" spacing={2} alignItems="center">
              <TextField
                label="Priority"
                type="number"
                value={draft.priority}
                onChange={(e) => setDraft({ ...draft, priority: Number(e.target.value) })}
                sx={{ width: 120 }}
              />
              <FormControlLabel
                control={<Switch checked={draft.transferOwner} onChange={(e) => setDraft({ ...draft, transferOwner: e.target.checked })} />}
                label="Transfer owner/email (user successor)"
              />
            </Stack>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="contained" disabled={!draft.name || !draft.successor || createMut.isPending} onClick={() => createMut.mutate()}>
            Create
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
