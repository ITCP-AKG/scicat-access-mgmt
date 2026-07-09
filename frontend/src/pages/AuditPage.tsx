import { useState } from 'react';
import {
  Box,
  Chip,
  Dialog,
  DialogContent,
  DialogTitle,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery } from '@tanstack/react-query';
import { AuditApi } from '../api/endpoints';
import type { AuditEntry } from '../api/types';

const ENTITY_TYPES = ['', 'group', 'membership', 'grant', 'projection', 'transfer', 'user'];

export default function AuditPage() {
  const [actor, setActor] = useState('');
  const [entityType, setEntityType] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [selected, setSelected] = useState<AuditEntry | null>(null);

  const { data: entries = [], isLoading } = useQuery({
    queryKey: ['audit', actor, entityType, from, to],
    queryFn: () =>
      AuditApi.list({
        actor: actor || undefined,
        entityType: entityType || undefined,
        from: from ? new Date(from).toISOString() : undefined,
        to: to ? new Date(to).toISOString() : undefined,
      }),
  });

  const columns: GridColDef[] = [
    { field: 'at', headerName: 'When', width: 185, valueFormatter: (v) => new Date(v.value).toLocaleString() },
    {
      field: 'actorKind',
      headerName: 'Source',
      width: 110,
      renderCell: (p) => (
        <Chip size="small" label={p.value} color={p.value === 'system' ? 'info' : 'default'} />
      ),
    },
    { field: 'actor', headerName: 'Actor', flex: 1 },
    { field: 'action', headerName: 'Action', flex: 1 },
    { field: 'entityType', headerName: 'Entity', width: 120 },
    { field: 'entityId', headerName: 'Target', flex: 1 },
    { field: 'summary', headerName: 'Summary', flex: 1.5 },
  ];

  return (
    <Box>
      <Typography variant="h5" mb={2}>
        Audit Log
      </Typography>
      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={2} flexWrap="wrap">
          <TextField label="Actor" size="small" value={actor} onChange={(e) => setActor(e.target.value)} />
          <TextField
            select
            label="Entity type"
            size="small"
            value={entityType}
            onChange={(e) => setEntityType(e.target.value)}
            sx={{ width: 160 }}
          >
            {ENTITY_TYPES.map((t) => (
              <MenuItem key={t} value={t}>
                {t || 'any'}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="From"
            type="datetime-local"
            size="small"
            InputLabelProps={{ shrink: true }}
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
          <TextField
            label="To"
            type="datetime-local"
            size="small"
            InputLabelProps={{ shrink: true }}
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
        </Stack>
      </Paper>
      <div style={{ height: 560, width: '100%' }}>
        <DataGrid
          rows={entries}
          columns={columns}
          getRowId={(r) => r.id}
          loading={isLoading}
          onRowClick={(p) => setSelected(p.row as AuditEntry)}
          disableRowSelectionOnClick
          density="compact"
        />
      </div>

      <Dialog open={!!selected} onClose={() => setSelected(null)} fullWidth maxWidth="md">
        <DialogTitle>
          {selected?.action} — {selected?.entityType}/{selected?.entityId}
        </DialogTitle>
        <DialogContent>
          <Stack direction="row" spacing={4}>
            <Box flex={1}>
              <Typography variant="subtitle2">Before</Typography>
              <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12 }}>
                {selected?.before ? JSON.stringify(selected.before, null, 2) : '—'}
              </pre>
            </Box>
            <Box flex={1}>
              <Typography variant="subtitle2">After</Typography>
              <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12 }}>
                {selected?.after ? JSON.stringify(selected.after, null, 2) : '—'}
              </pre>
            </Box>
          </Stack>
        </DialogContent>
      </Dialog>
    </Box>
  );
}
