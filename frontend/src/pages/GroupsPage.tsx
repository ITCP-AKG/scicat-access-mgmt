import { useState } from 'react';
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
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { GroupsApi } from '../api/endpoints';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import type { GroupCategory } from '../api/types';

const CATEGORIES: GroupCategory[] = ['research-group', 'project', 'proposal', 'instrument', 'other'];

export default function GroupsPage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: groups = [], isLoading } = useQuery({
    queryKey: ['groups'],
    queryFn: () => GroupsApi.list(),
  });

  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState<GroupCategory>('research-group');
  const [error, setError] = useState<string | null>(null);

  const createMut = useMutation({
    mutationFn: () => GroupsApi.create({ name, description, category }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['groups'] });
      setOpen(false);
      setName('');
      setDescription('');
      setError(null);
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Failed to create group'),
  });

  const columns: GridColDef[] = [
    { field: 'name', headerName: 'Name', flex: 1 },
    { field: 'category', headerName: 'Category', width: 150 },
    { field: 'description', headerName: 'Description', flex: 1.5 },
    { field: 'status', headerName: 'Status', width: 110 },
  ];

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h5">Access Groups</Typography>
        {me?.isAdmin && (
          <Button variant="contained" onClick={() => setOpen(true)}>
            New group
          </Button>
        )}
      </Stack>
      <div style={{ height: 560, width: '100%' }}>
        <DataGrid
          rows={groups}
          columns={columns}
          getRowId={(r) => r.name}
          loading={isLoading}
          onRowClick={(p) => navigate(`/groups/${encodeURIComponent(p.id as string)}`)}
          disableRowSelectionOnClick
        />
      </div>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Create group</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} fullWidth />
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
            <TextField
              label="Description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              multiline
              minRows={2}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="contained" disabled={!name || createMut.isPending} onClick={() => createMut.mutate()}>
            Create
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
