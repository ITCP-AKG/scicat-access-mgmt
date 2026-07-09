import { useState } from 'react';
import {
  Box,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { DataGrid, type GridColDef, type GridValidRowModel } from '@mui/x-data-grid';
import { useQuery } from '@tanstack/react-query';
import { ExpiryApi } from '../api/endpoints';

const WINDOWS = [7, 14, 30, 60, 90];

const fmt = (v: { value: string | null }) =>
  v.value ? new Date(v.value).toLocaleString() : '—';

const membershipColumns: GridColDef[] = [
  { field: 'userDisplay', headerName: 'User', flex: 1 },
  { field: 'groupName', headerName: 'Group', flex: 1 },
  { field: 'status', headerName: 'Status', width: 110 },
  { field: 'expiresAt', headerName: 'Expires', width: 190, valueFormatter: fmt },
];

const grantColumns: GridColDef[] = [
  { field: 'groupName', headerName: 'Group', flex: 1 },
  { field: 'resourceType', headerName: 'Type', width: 130 },
  { field: 'resourceId', headerName: 'Resource', flex: 1 },
  { field: 'mode', headerName: 'Mode', width: 100 },
  { field: 'expiresAt', headerName: 'Expires', width: 190, valueFormatter: fmt },
];

function Section({
  title,
  rows,
  columns,
}: {
  title: string;
  rows: GridValidRowModel[];
  columns: GridColDef[];
}) {
  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="h6" mb={1}>
        {title} ({rows.length})
      </Typography>
      <div style={{ height: 320, width: '100%' }}>
        <DataGrid
          rows={rows}
          columns={columns}
          getRowId={(r) => (r.id as string) ?? `${r.groupName}:${r.resourceId}`}
          disableRowSelectionOnClick
          density="compact"
        />
      </div>
    </Paper>
  );
}

export default function ExpiryDashboard() {
  const [withinDays, setWithinDays] = useState(30);
  const { data } = useQuery({
    queryKey: ['expiry', withinDays],
    queryFn: () => ExpiryApi.dashboard(withinDays),
  });

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h5">Expiry Dashboard</Typography>
        <TextField
          select
          label="Window"
          size="small"
          value={withinDays}
          onChange={(e) => setWithinDays(Number(e.target.value))}
          sx={{ width: 160 }}
        >
          {WINDOWS.map((d) => (
            <MenuItem key={d} value={d}>
              within {d} days
            </MenuItem>
          ))}
        </TextField>
      </Stack>
      <Stack spacing={2}>
        <Section
          title="Expiring soon"
          rows={data?.expiringSoon ?? []}
          columns={membershipColumns}
        />
        <Section
          title="Recently expired"
          rows={data?.recentlyExpired ?? []}
          columns={membershipColumns}
        />
        <Section
          title="Expiring grants"
          rows={data?.expiringGrants ?? []}
          columns={grantColumns}
        />
      </Stack>
    </Box>
  );
}
