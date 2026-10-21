import { useMemo, useState } from 'react';
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
  FormControlLabel,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import { DataGrid, type GridColDef, type GridRowSelectionModel } from '@mui/x-data-grid';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { GrantsApi, GroupsApi } from '../api/endpoints';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { useDebounced } from '../hooks/useDebounced';
import TemporalWindowField from '../components/TemporalWindowField';
import { EMPTY_WINDOW, windowError, type TemporalWindow } from '../lib/forms';
import type { BulkResult, GrantMode, ResourceGrant, ResourceSummary, ResourceType } from '../api/types';

// Only these SciCat types carry ownerGroup/accessGroups.
const RESOURCE_TYPES: ResourceType[] = ['dataset', 'origdatablock', 'proposal', 'sample'];
const PAGE_SIZE = 50;
const OPEN = new Set(['active', 'scheduled']);
const fmtDate = (v: { value: string | null }) => (v.value ? new Date(v.value).toLocaleString() : '—');

function BrowseAndApply() {
  const { me } = useAuth();
  const isAdmin = !!me?.isAdmin;
  const qc = useQueryClient();
  const [resourceType, setResourceType] = useState<ResourceType>('dataset');
  const [search, setSearch] = useState('');
  const [ownerFilter, setOwnerFilter] = useState('');
  const [page, setPage] = useState(0);
  const [selection, setSelection] = useState<GridRowSelectionModel>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [groupName, setGroupName] = useState('');
  const [mode, setMode] = useState<GrantMode>('access');
  const [grantWindow, setGrantWindow] = useState<TemporalWindow>(EMPTY_WINDOW);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BulkResult | null>(null);

  const q = useDebounced(search.trim(), 300);
  const owner = useDebounced(ownerFilter.trim(), 300);
  const { data: resources, isFetching } = useQuery({
    queryKey: ['resources', resourceType, q, owner, page],
    queryFn: () =>
      GrantsApi.browse(resourceType, {
        q: q || undefined,
        ownerGroup: owner || undefined,
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
  });

  const { data: groups = [] } = useQuery({ queryKey: ['groups'], queryFn: () => GroupsApi.list() });
  // Non-admins may only grant their own (active) groups.
  const grantable = groups.filter(
    (g) => g.status === 'active' && (isAdmin || me?.managerOf.includes(g.name)),
  );

  function resetPaging() {
    setPage(0);
  }

  const applyMut = useMutation({
    mutationFn: () =>
      GrantsApi.apply({
        groupName,
        resourceType,
        resourceIds: selection.map((id) => String(id)),
        mode,
        effectiveFrom: grantWindow.effectiveFrom,
        expiresAt: grantWindow.expiresAt,
      }),
    onSuccess: (res) => {
      setResult(res);
      setDialogOpen(false);
      setSelection(res.items.filter((i) => !i.ok).map((i) => i.resourceId));
      setGrantWindow(EMPTY_WINDOW);
      setError(null);
      qc.invalidateQueries({ queryKey: ['resources'] });
      qc.invalidateQueries({ queryKey: ['grants'] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Failed to apply grant'),
  });

  const columns: GridColDef<ResourceSummary>[] = useMemo(
    () => [
      { field: 'id', headerName: 'ID', flex: 1 },
      { field: 'label', headerName: 'Label', flex: 1.2 },
      { field: 'ownerGroup', headerName: 'Owner group', width: 180 },
      {
        field: 'accessGroups',
        headerName: 'Access groups',
        flex: 1,
        renderCell: (p) => (p.value as string[]).filter(Boolean).join(', '),
      },
    ],
    [],
  );

  const windowProblem = windowError(grantWindow);

  return (
    <Box>
      {!isAdmin && (
        <Alert severity="info" sx={{ mb: 2 }}>
          You see resources owned by your own groups and can grant access to the groups you manage.
        </Alert>
      )}
      <Stack direction="row" spacing={2} mb={2} alignItems="center">
        <TextField
          select
          size="small"
          label="Resource type"
          value={resourceType}
          onChange={(e) => {
            setResourceType(e.target.value as ResourceType);
            setSelection([]);
            resetPaging();
          }}
          sx={{ width: 180 }}
        >
          {RESOURCE_TYPES.map((t) => (
            <MenuItem key={t} value={t}>
              {t}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          size="small"
          label="Search name / id"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            resetPaging();
          }}
          sx={{ flexGrow: 1 }}
        />
        <TextField
          size="small"
          label="Owner group"
          value={ownerFilter}
          onChange={(e) => {
            setOwnerFilter(e.target.value);
            resetPaging();
          }}
          sx={{ width: 180 }}
        />
        <Button
          variant="contained"
          disabled={selection.length === 0 || grantable.length === 0}
          onClick={() => {
            setResult(null);
            setDialogOpen(true);
          }}
        >
          Apply group ({selection.length})
        </Button>
      </Stack>

      {result && (
        <Alert severity={result.failed ? 'warning' : 'success'} sx={{ mb: 2 }} onClose={() => setResult(null)}>
          Applied to {result.succeeded}/{result.total} resource(s).
          {result.failed > 0 && (
            <>
              {' '}Failed items stay selected.
              <ul style={{ margin: '4px 0 0 16px' }}>
                {result.items
                  .filter((i) => !i.ok)
                  .map((i) => (
                    <li key={i.resourceId}>
                      {i.resourceId}: {i.error}
                    </li>
                  ))}
              </ul>
            </>
          )}
        </Alert>
      )}

      <div style={{ height: 520, width: '100%' }}>
        <DataGrid
          rows={resources?.items ?? []}
          columns={columns}
          getRowId={(r) => r.id}
          loading={isFetching}
          checkboxSelection
          keepNonExistentRowsSelected
          rowSelectionModel={selection}
          onRowSelectionModelChange={setSelection}
          disableRowSelectionOnClick
          hideFooter
        />
      </div>
      <Stack direction="row" spacing={2} alignItems="center" justifyContent="flex-end" mt={1}>
        <Typography variant="body2" color="text.secondary">
          Page {page + 1} · {selection.length} selected
        </Typography>
        <Button size="small" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
          Previous
        </Button>
        <Button size="small" disabled={!resources?.hasMore} onClick={() => setPage((p) => p + 1)}>
          Next
        </Button>
      </Stack>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Apply group to {selection.length} resource(s)</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField select label="Group" value={groupName} onChange={(e) => setGroupName(e.target.value)}>
              {grantable.map((g) => (
                <MenuItem key={g.name} value={g.name}>
                  {g.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="Mode"
              value={mode}
              onChange={(e) => setMode(e.target.value as GrantMode)}
              helperText={
                mode === 'owner'
                  ? 'Sets ownerGroup; the previous owner is restored when the grant ends.'
                  : 'Adds the group to accessGroups (read access for its members).'
              }
            >
              <MenuItem value="access">access</MenuItem>
              {isAdmin && <MenuItem value="owner">owner</MenuItem>}
            </TextField>
            <Typography variant="caption" color="text.secondary">
              Optional time-bounded grant (activated/withdrawn by the scheduler):
            </Typography>
            <TemporalWindowField value={grantWindow} onChange={setGrantWindow} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!groupName || !!windowProblem || applyMut.isPending}
            onClick={() => applyMut.mutate()}
          >
            Apply
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

function AppliedGrants() {
  const { me } = useAuth();
  const isAdmin = !!me?.isAdmin;
  const qc = useQueryClient();
  const [groupFilter, setGroupFilter] = useState('');
  const [showEnded, setShowEnded] = useState(false);
  const [message, setMessage] = useState<{ severity: 'success' | 'warning' | 'error'; text: string } | null>(null);
  const { data: grants = [], isLoading } = useQuery({
    queryKey: ['grants', 'all'],
    queryFn: () => GrantsApi.list(),
  });

  const removeMut = useMutation({
    mutationFn: (id: string) => GrantsApi.remove(id),
    onSuccess: (pending) => {
      qc.invalidateQueries({ queryKey: ['grants'] });
      setMessage(
        pending?.pendingRemoval
          ? { severity: 'warning', text: `SciCat refused the withdrawal (${pending.lastError}); it will be retried.` }
          : { severity: 'success', text: 'Grant withdrawn.' },
      );
    },
    onError: (e) => setMessage({ severity: 'error', text: e instanceof ApiError ? e.message : 'Failed to remove' }),
  });

  const canRemove = (g: ResourceGrant) =>
    OPEN.has(g.status) && (isAdmin || (g.mode === 'access' && !!me?.managerOf.includes(g.groupName)));

  const rows = grants.filter(
    (g) => (showEnded || OPEN.has(g.status)) && (!groupFilter || g.groupName.includes(groupFilter)),
  );

  const columns: GridColDef<ResourceGrant>[] = [
    { field: 'groupName', headerName: 'Group', width: 160 },
    { field: 'resourceType', headerName: 'Type', width: 120 },
    { field: 'resourceId', headerName: 'Resource', flex: 1.4 },
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
            color={p.row.pendingRemoval || p.row.lastError ? 'warning' : p.value === 'active' ? 'success' : 'default'}
          />
        </Tooltip>
      ),
    },
    { field: 'expiresAt', headerName: 'Expires', width: 170, valueFormatter: fmtDate },
    {
      field: 'actions',
      headerName: '',
      width: 100,
      sortable: false,
      renderCell: (p) =>
        canRemove(p.row) && (
          <Button size="small" color="error" onClick={() => removeMut.mutate(p.row.id)}>
            {p.row.pendingRemoval ? 'Retry' : 'Remove'}
          </Button>
        ),
    },
  ];

  return (
    <Box>
      {message && (
        <Alert severity={message.severity} sx={{ mb: 2 }} onClose={() => setMessage(null)}>
          {message.text}
        </Alert>
      )}
      <Stack direction="row" spacing={2} mb={2} alignItems="center">
        <TextField size="small" label="Group" value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)} />
        <FormControlLabel
          control={<Checkbox size="small" checked={showEnded} onChange={(e) => setShowEnded(e.target.checked)} />}
          label="Show ended"
        />
      </Stack>
      <div style={{ height: 560, width: '100%' }}>
        <DataGrid rows={rows} columns={columns} getRowId={(r) => r.id} loading={isLoading} disableRowSelectionOnClick density="compact" />
      </div>
    </Box>
  );
}

export default function ResourceGrantsPage() {
  const [tab, setTab] = useState(0);
  return (
    <Box>
      <Typography variant="h5" mb={1}>
        Resource Grants
      </Typography>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Browse & apply" />
        <Tab label="Applied grants" />
      </Tabs>
      {tab === 0 ? <BrowseAndApply /> : <AppliedGrants />}
    </Box>
  );
}
