import { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Radio,
  RadioGroup,
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
import { UserMultiPicker } from '../components/UserPicker';
import { useDebounced } from '../hooks/useDebounced';
import { CATEGORIES } from '../lib/forms';
import type { GroupCategory, NameCheck } from '../api/types';

function nameProblem(check: NameCheck | undefined): string | null {
  if (!check || !check.name) return null;
  if (check.reserved) return 'Reserved SciCat group name';
  if (!check.valid) return 'Use letters, digits and . _ : @ + - (max 64, no spaces)';
  if (check.exists) return 'A group with this name already exists';
  if (check.collidesWithUser) return "Collides with a user's personal group";
  return null;
}

function CreateGroupDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState<GroupCategory>('research-group');
  const [managers, setManagers] = useState<string[]>([]);
  const [importHolders, setImportHolders] = useState<'' | 'adopt' | 'strip'>('');
  const [error, setError] = useState<string | null>(null);

  const checkedName = useDebounced(name.trim(), 300);
  const { data: check } = useQuery({
    queryKey: ['name-check', checkedName],
    queryFn: () => GroupsApi.nameCheck(checkedName),
    enabled: open && checkedName.length > 0,
  });
  const current = check?.name === name.trim() ? check : undefined;
  const problem = nameProblem(current);
  const holders = current?.holders ?? 0;

  function reset() {
    setName('');
    setDescription('');
    setManagers([]);
    setImportHolders('');
    setError(null);
  }

  const createMut = useMutation({
    mutationFn: () =>
      GroupsApi.create({
        name: name.trim(),
        description,
        category,
        managers,
        importHolders: holders ? importHolders === 'adopt' : undefined,
      }),
    onSuccess: (group) => {
      qc.invalidateQueries({ queryKey: ['groups'] });
      // a departed user made manager is reactivated
      qc.invalidateQueries({ queryKey: ['user'] });
      qc.invalidateQueries({ queryKey: ['user-search'] });
      reset();
      onClose();
      navigate(`/groups/${encodeURIComponent(group.name)}`);
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Failed to create group'),
  });

  const ready = !!name.trim() && !!current && !problem && (!holders || importHolders !== '');

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Create group</DialogTitle>
      <DialogContent>
        <Stack spacing={2} mt={1}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            error={!!problem}
            helperText={problem ?? 'The exact string SciCat will see in ownerGroup/accessGroups'}
            fullWidth
            autoFocus
          />
          {holders > 0 && !problem && (
            <Alert severity="warning">
              <Typography variant="body2" mb={1}>
                {holders} user(s) already carry “{name.trim()}” in SciCat. Once the group is
                managed here, only its members keep it.
              </Typography>
              <RadioGroup
                value={importHolders}
                onChange={(e) => setImportHolders(e.target.value as 'adopt' | 'strip')}
              >
                <FormControlLabel value="adopt" control={<Radio size="small" />} label="Add them as members" />
                <FormControlLabel value="strip" control={<Radio size="small" />} label="Remove it from them" />
              </RadioGroup>
            </Alert>
          )}
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
          <UserMultiPicker value={managers} onChange={setManagers} />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!ready || createMut.isPending} onClick={() => createMut.mutate()}>
          Create
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default function GroupsPage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const { data: groups = [], isLoading } = useQuery({
    queryKey: ['groups'],
    queryFn: () => GroupsApi.list(),
  });
  const [open, setOpen] = useState(false);

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
      <CreateGroupDialog open={open} onClose={() => setOpen(false)} />
    </Box>
  );
}
