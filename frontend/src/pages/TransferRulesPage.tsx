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
  Tooltip,
  Typography,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { GroupsApi, TransfersApi, UsersApi } from '../api/endpoints';
import { ApiError } from '../api/client';
import UserPicker from '../components/UserPicker';
import { CATEGORIES } from '../lib/forms';
import type {
  Departure,
  DirectoryUser,
  SuccessorType,
  TransferRecord,
  TransferRule,
  TransferRuleCreate,
} from '../api/types';

const EMPTY: TransferRuleCreate = {
  name: '',
  match: { userId: null, category: null, groupName: null },
  successorType: 'group',
  successor: '',
  transferOwner: true,
  priority: 100,
  enabled: true,
};

const outcomeColor = (o: string) =>
  o === 'transferred' || o === 'resolved' ? 'success' : o === 'pending_manual' ? 'warning' : 'error';
const fmtDate = (v: { value: string | null }) => (v.value ? new Date(v.value).toLocaleString() : '—');

/** A stored userId shown as a picker value (resolved to the directory entry). */
function useDirectoryUser(userId: string | null) {
  return useQuery({
    queryKey: ['user', userId],
    queryFn: () => UsersApi.get(userId as string),
    enabled: !!userId,
    staleTime: 300_000,
    retry: false,
  }).data;
}

function RuleDialog({ rule, onClose }: { rule: TransferRule | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<TransferRuleCreate>(rule ? { ...rule } : EMPTY);
  const [error, setError] = useState<string | null>(null);
  const { data: groups = [] } = useQuery({ queryKey: ['groups'], queryFn: () => GroupsApi.list() });
  const matchUser = useDirectoryUser(draft.match.userId);
  const successorUser = useDirectoryUser(draft.successorType === 'user' ? draft.successor : null);

  const saveMut = useMutation({
    mutationFn: () => (rule ? TransfersApi.updateRule(rule.id, draft) : TransfersApi.createRule(draft)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['transfer-rules'] });
      onClose();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Failed to save rule'),
  });

  const setMatch = (patch: Partial<TransferRuleCreate['match']>) =>
    setDraft({ ...draft, match: { ...draft.match, ...patch } });

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{rule ? 'Edit transfer rule' : 'Create transfer rule'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} mt={1}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField label="Name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          <Typography variant="subtitle2">
            Applies to departing users matching all of (leave blank for any):
          </Typography>
          <UserPicker
            label="Specific user"
            value={matchUser ?? null}
            onChange={(u: DirectoryUser | null) => setMatch({ userId: u?.userId ?? null })}
          />
          <Stack direction="row" spacing={2}>
            <TextField
              select
              label="Was member of group"
              value={draft.match.groupName ?? ''}
              onChange={(e) => setMatch({ groupName: e.target.value || null })}
              sx={{ flex: 1 }}
            >
              <MenuItem value="">any</MenuItem>
              {groups.map((g) => (
                <MenuItem key={g.name} value={g.name}>
                  {g.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="…of a group in category"
              value={draft.match.category ?? ''}
              onChange={(e) => setMatch({ category: e.target.value || null })}
              sx={{ flex: 1 }}
            >
              <MenuItem value="">any</MenuItem>
              {CATEGORIES.map((c) => (
                <MenuItem key={c} value={c}>
                  {c}
                </MenuItem>
              ))}
            </TextField>
          </Stack>
          <Typography variant="subtitle2">Hand their resources to:</Typography>
          <Stack direction="row" spacing={2}>
            <TextField
              select
              label="Successor type"
              value={draft.successorType}
              onChange={(e) => setDraft({ ...draft, successorType: e.target.value as SuccessorType, successor: '' })}
              sx={{ width: 160 }}
            >
              <MenuItem value="group">group</MenuItem>
              <MenuItem value="user">user</MenuItem>
            </TextField>
            <Box sx={{ flexGrow: 1 }}>
              {draft.successorType === 'group' ? (
                <TextField
                  select
                  fullWidth
                  label="Successor group"
                  value={draft.successor}
                  onChange={(e) => setDraft({ ...draft, successor: e.target.value })}
                >
                  {groups.map((g) => (
                    <MenuItem key={g.name} value={g.name}>
                      {g.name}
                    </MenuItem>
                  ))}
                </TextField>
              ) : (
                <UserPicker
                  label="Successor user"
                  value={successorUser ?? null}
                  onChange={(u) => setDraft({ ...draft, successor: u?.userId ?? '' })}
                />
              )}
            </Box>
          </Stack>
          <Stack direction="row" spacing={2} alignItems="center">
            <TextField
              label="Priority"
              type="number"
              size="small"
              value={draft.priority}
              onChange={(e) => setDraft({ ...draft, priority: Number(e.target.value) })}
              helperText="Lower runs first"
              sx={{ width: 120 }}
            />
            <FormControlLabel
              control={
                <Switch
                  checked={draft.transferOwner}
                  disabled={draft.successorType !== 'user'}
                  onChange={(e) => setDraft({ ...draft, transferOwner: e.target.checked })}
                />
              }
              label="Also hand over contact fields (owner, emails)"
            />
            <FormControlLabel
              control={<Switch checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />}
              label="Enabled"
            />
          </Stack>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={!draft.name || !draft.successor || saveMut.isPending}
          onClick={() => saveMut.mutate()}
        >
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default function TransferRulesPage() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<TransferRule | 'new' | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const { data: rules = [], isLoading } = useQuery({
    queryKey: ['transfer-rules'],
    queryFn: () => TransfersApi.listRules(),
  });
  const { data: batches = [] } = useQuery({
    queryKey: ['transfer-batches'],
    queryFn: () => TransfersApi.batches(),
  });
  const { data: records = [] } = useQuery({
    queryKey: ['transfer-records'],
    queryFn: () => TransfersApi.records(),
  });

  const pendingManual = records.filter((r) => r.outcome === 'pending_manual');
  const failed = records.filter((r) => r.outcome === 'failed');

  const deleteMut = useMutation({
    mutationFn: (id: string) => TransfersApi.deleteRule(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['transfer-rules'] }),
  });
  const retryMut = useMutation({
    mutationFn: (batchId: string) => TransfersApi.retryBatch(batchId),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['transfer-records'] });
      qc.invalidateQueries({ queryKey: ['transfer-batches'] });
      const done = res.records.filter((r) => r.outcome === 'transferred' || r.outcome === 'resolved').length;
      setToast(`Retry: ${res.records.length} resource(s) re-evaluated, ${done} done${res.errors.length ? `; ${res.errors.join('; ')}` : ''}`);
    },
    onError: (e) => setToast(e instanceof ApiError ? e.message : 'Retry failed'),
  });

  const ruleColumns: GridColDef<TransferRule>[] = [
    { field: 'priority', headerName: 'Prio', width: 70 },
    { field: 'name', headerName: 'Name', flex: 1 },
    {
      field: 'match',
      headerName: 'Matches',
      flex: 1,
      renderCell: (p) =>
        [
          p.row.match.userId && `user ${p.row.match.userId}`,
          p.row.match.groupName && `group ${p.row.match.groupName}`,
          p.row.match.category && `category ${p.row.match.category}`,
        ]
          .filter(Boolean)
          .join(' / ') || 'anyone',
    },
    {
      field: 'successor',
      headerName: 'Successor',
      flex: 1,
      renderCell: (p) => `${p.row.successorType}: ${p.value}${p.row.transferOwner && p.row.successorType === 'user' ? ' (+contact)' : ''}`,
    },
    {
      field: 'enabled',
      headerName: 'Enabled',
      width: 90,
      renderCell: (p) => <Chip size="small" label={p.value ? 'on' : 'off'} color={p.value ? 'success' : 'default'} />,
    },
    {
      field: 'actions',
      headerName: '',
      width: 150,
      sortable: false,
      renderCell: (p) => (
        <Stack direction="row" spacing={1}>
          <Button size="small" onClick={() => setEditing(p.row)}>
            Edit
          </Button>
          <Button size="small" color="error" onClick={() => deleteMut.mutate(p.row.id)}>
            Delete
          </Button>
        </Stack>
      ),
    },
  ];

  const batchColumns: GridColDef<Departure>[] = [
    { field: 'at', headerName: 'When', width: 175, valueFormatter: fmtDate },
    { field: 'userId', headerName: 'User', flex: 1 },
    { field: 'reason', headerName: 'Reason', width: 100 },
    { field: 'groups', headerName: 'Groups', flex: 1, renderCell: (p) => (p.value as string[]).join(', ') || '—' },
    {
      field: 'needsRetry',
      headerName: 'State',
      width: 130,
      renderCell: (p) => {
        const open = records.filter((r) => r.batchId === p.row.id && (r.outcome === 'pending_manual' || r.outcome === 'failed')).length;
        if (p.value) return <Chip size="small" color="error" label="errors" />;
        return open ? <Chip size="small" color="warning" label={`${open} open`} /> : <Chip size="small" color="success" label="done" />;
      },
    },
    {
      field: 'actions',
      headerName: '',
      width: 90,
      sortable: false,
      renderCell: (p) => (
        <Button size="small" disabled={retryMut.isPending} onClick={() => retryMut.mutate(p.row.id)}>
          Retry
        </Button>
      ),
    },
  ];

  const recordColumns: GridColDef<TransferRecord>[] = [
    { field: 'at', headerName: 'When', width: 175, valueFormatter: fmtDate },
    { field: 'fromUserId', headerName: 'From user', flex: 0.8 },
    { field: 'resourceType', headerName: 'Type', width: 110 },
    { field: 'resourceId', headerName: 'Resource', flex: 1.2 },
    {
      field: 'after',
      headerName: 'Changed',
      flex: 1.2,
      renderCell: (p) =>
        Object.entries(p.row.after ?? {})
          .map(([k, v]) => `${k}=${String(v)}`)
          .join(', ') || '—',
    },
    {
      field: 'outcome',
      headerName: 'Outcome',
      width: 150,
      renderCell: (p) => (
        <Tooltip title={[p.row.error, ...(p.row.notes ?? [])].filter(Boolean).join(' · ')}>
          <Chip size="small" label={p.value} color={outcomeColor(p.value)} />
        </Tooltip>
      ),
    },
  ];

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h5">Ownership Transfers</Typography>
        <Button variant="contained" onClick={() => setEditing('new')}>
          New rule
        </Button>
      </Stack>
      <Typography variant="body2" color="text.secondary" mb={2}>
        When a user is deactivated or their last membership expires, resources they personally own
        (their personal owner group, or contact fields naming them) are handed to the first matching
        rule's successor. Data owned by shared groups stays with the group.
      </Typography>

      {(pendingManual.length > 0 || failed.length > 0) && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {pendingManual.length} resource(s) need manual handling (no matching rule, or contact fields
          not handed over); {failed.length} failed. Add or fix a rule, then retry the departure.
        </Alert>
      )}

      <Paper sx={{ p: 2, mb: 2 }}>
        <Typography variant="h6" mb={1}>
          Rules
        </Typography>
        <div style={{ height: 280, width: '100%' }}>
          <DataGrid rows={rules} columns={ruleColumns} getRowId={(r) => r.id} loading={isLoading} disableRowSelectionOnClick density="compact" />
        </div>
      </Paper>

      <Paper sx={{ p: 2, mb: 2 }}>
        <Typography variant="h6" mb={1}>
          Departures
        </Typography>
        <div style={{ height: 260, width: '100%' }}>
          <DataGrid rows={batches} columns={batchColumns} getRowId={(r) => r.id} disableRowSelectionOnClick density="compact" />
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

      {editing && <RuleDialog rule={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      {toast && (
        <Alert severity="info" sx={{ position: 'fixed', bottom: 16, right: 16 }} onClose={() => setToast(null)}>
          {toast}
        </Alert>
      )}
    </Box>
  );
}
