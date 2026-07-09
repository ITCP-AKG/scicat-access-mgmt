import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import {
  DataGrid,
  type GridColDef,
  type GridRowSelectionModel,
} from '@mui/x-data-grid';
import { useMutation, useQuery } from '@tanstack/react-query';
import { GrantsApi, GroupsApi } from '../api/endpoints';
import { ApiError } from '../api/client';
import TemporalWindowField, { type TemporalWindow } from '../components/TemporalWindowField';
import type { BulkResult, GrantMode, ResourceType } from '../api/types';

const RESOURCE_TYPES: ResourceType[] = [
  'dataset',
  'origdatablock',
  'proposal',
  'sample',
  'instrument',
  'job',
];

export default function ResourceGrantsPage() {
  const [resourceType, setResourceType] = useState<ResourceType>('dataset');
  const [search, setSearch] = useState('');
  const [selection, setSelection] = useState<GridRowSelectionModel>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [groupName, setGroupName] = useState('');
  const [mode, setMode] = useState<GrantMode>('access');
  const [window, setWindow] = useState<TemporalWindow>({ effectiveFrom: null, expiresAt: null });
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BulkResult | null>(null);

  const { data: page, isLoading, refetch } = useQuery({
    queryKey: ['resources', resourceType, search],
    queryFn: () => GrantsApi.browse(resourceType, { q: search || undefined }),
  });

  const { data: groups = [] } = useQuery({
    queryKey: ['groups'],
    queryFn: () => GroupsApi.list(),
  });

  const applyMut = useMutation({
    mutationFn: () =>
      GrantsApi.apply({
        groupName,
        resourceType,
        resourceIds: selection.map((id) => String(id)),
        mode,
        effectiveFrom: window.effectiveFrom,
        expiresAt: window.expiresAt,
      }),
    onSuccess: (res) => {
      setResult(res);
      setDialogOpen(false);
      setSelection([]);
      setWindow({ effectiveFrom: null, expiresAt: null });
      setError(null);
      refetch();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Failed to apply grant'),
  });

  const columns: GridColDef[] = useMemo(
    () => [
      { field: 'id', headerName: 'ID', flex: 1 },
      { field: 'label', headerName: 'Label', flex: 1.2 },
      { field: 'ownerGroup', headerName: 'Owner group', width: 180 },
      {
        field: 'accessGroups',
        headerName: 'Access groups',
        flex: 1,
        renderCell: (p) => ((p.value as string[]) || []).join(', '),
      },
    ],
    [],
  );

  return (
    <Box>
      <Typography variant="h5" mb={2}>
        Resource Grants
      </Typography>

      <Stack direction="row" spacing={2} mb={2} alignItems="center">
        <TextField
          select
          label="Resource type"
          value={resourceType}
          onChange={(e) => {
            setResourceType(e.target.value as ResourceType);
            setSelection([]);
          }}
          sx={{ width: 200 }}
        >
          {RESOURCE_TYPES.map((t) => (
            <MenuItem key={t} value={t}>
              {t}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="Search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          sx={{ flexGrow: 1 }}
        />
        <Button
          variant="contained"
          disabled={selection.length === 0}
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
            <ul style={{ margin: '4px 0 0 16px' }}>
              {result.items
                .filter((i) => !i.ok)
                .map((i) => (
                  <li key={i.resourceId}>
                    {i.resourceId}: {i.error}
                  </li>
                ))}
            </ul>
          )}
        </Alert>
      )}

      <div style={{ height: 560, width: '100%' }}>
        <DataGrid
          rows={page?.items ?? []}
          columns={columns}
          getRowId={(r) => r.id}
          loading={isLoading}
          checkboxSelection
          rowSelectionModel={selection}
          onRowSelectionModelChange={setSelection}
          disableRowSelectionOnClick
        />
      </div>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Apply group to {selection.length} resource(s)</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField
              select
              label="Group"
              value={groupName}
              onChange={(e) => setGroupName(e.target.value)}
            >
              {groups.map((g) => (
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
                  ? 'Sets ownerGroup (captures the previous owner).'
                  : 'Adds the group to accessGroups.'
              }
            >
              <MenuItem value="access">access</MenuItem>
              <MenuItem value="owner">owner</MenuItem>
            </TextField>
            <Typography variant="caption" color="text.secondary">
              Optional time-bounded grant (activated/withdrawn by the scheduler):
            </Typography>
            <TemporalWindowField value={window} onChange={setWindow} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!groupName || applyMut.isPending}
            onClick={() => applyMut.mutate()}
          >
            Apply
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
