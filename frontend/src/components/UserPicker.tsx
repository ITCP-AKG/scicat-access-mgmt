import { useState } from 'react';
import { Autocomplete, Chip, CircularProgress, TextField } from '@mui/material';
import { useQueries, useQuery } from '@tanstack/react-query';
import { UsersApi } from '../api/endpoints';
import type { DirectoryUser } from '../api/types';
import { useDebounced } from '../hooks/useDebounced';
import { directoryUserQuery } from '../hooks/useDirectoryUser';
import { userLabel, userName } from '../lib/forms';

/** Debounced directory search; react-query keys by query, so stale answers never win. */
function useUserSearch(input: string) {
  const q = useDebounced(input.trim(), 250);
  const { data = [], isFetching } = useQuery({
    queryKey: ['user-search', q],
    queryFn: () => UsersApi.search(q),
    enabled: q.length > 0,
    staleTime: 30_000,
  });
  return { options: q ? data : [], loading: isFetching };
}

interface Props {
  value: DirectoryUser | null;
  onChange: (user: DirectoryUser | null) => void;
  label?: string;
}

export default function UserPicker({ value, onChange, label = 'Search user' }: Props) {
  const [input, setInput] = useState('');
  const { options, loading } = useUserSearch(input);
  return (
    <Autocomplete
      value={value}
      onChange={(_, v) => onChange(v)}
      options={options}
      filterOptions={(x) => x}
      getOptionLabel={userLabel}
      isOptionEqualToValue={(a, b) => a.userId === b.userId}
      onInputChange={(_, v) => setInput(v)}
      loading={loading}
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          size="small"
          InputProps={{
            ...params.InputProps,
            endAdornment: (
              <>
                {loading ? <CircularProgress size={16} /> : null}
                {params.InputProps.endAdornment}
              </>
            ),
          }}
        />
      )}
    />
  );
}

interface MultiProps {
  /** Directory userIds. */
  value: string[];
  onChange: (userIds: string[]) => void;
  label?: string;
}

/** Pick several users (e.g. group managers); stored ids are resolved to names. */
export function UserMultiPicker({ value, onChange, label = 'Managers' }: MultiProps) {
  const [input, setInput] = useState('');
  const { options, loading } = useUserSearch(input);
  const resolved = useQueries({ queries: value.map(directoryUserQuery) });
  const selected: DirectoryUser[] = value.map(
    (id, i) =>
      resolved[i]?.data ?? {
        userId: id,
        username: id,
        displayName: '',
        email: '',
        accessGroups: [],
        active: true,
      },
  );
  return (
    <Autocomplete
      multiple
      value={selected}
      onChange={(_, users) => onChange(users.map((u) => u.userId))}
      options={options}
      filterOptions={(x) => x}
      getOptionLabel={userLabel}
      isOptionEqualToValue={(a, b) => a.userId === b.userId}
      onInputChange={(_, v, reason) => reason === 'input' && setInput(v)}
      loading={loading}
      renderTags={(users, getTagProps) =>
        users.map((u, index) => (
          <Chip
            {...getTagProps({ index })}
            key={u.userId}
            size="small"
            label={userName(u)}
          />
        ))
      }
      renderInput={(params) => <TextField {...params} label={label} size="small" />}
    />
  );
}
