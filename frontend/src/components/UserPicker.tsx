import { useState } from 'react';
import { Autocomplete, CircularProgress, TextField } from '@mui/material';
import { UsersApi } from '../api/endpoints';
import type { DirectoryUser } from '../api/types';

interface Props {
  value: DirectoryUser | null;
  onChange: (user: DirectoryUser | null) => void;
}

// Debounced directory search via the backend /users endpoint (T025).
export default function UserPicker({ value, onChange }: Props) {
  const [options, setOptions] = useState<DirectoryUser[]>([]);
  const [loading, setLoading] = useState(false);

  let timer: ReturnType<typeof setTimeout> | undefined;
  function onInput(q: string) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(async () => {
      if (!q) {
        setOptions([]);
        return;
      }
      setLoading(true);
      try {
        setOptions(await UsersApi.search(q));
      } finally {
        setLoading(false);
      }
    }, 250);
  }

  return (
    <Autocomplete
      value={value}
      onChange={(_, v) => onChange(v)}
      options={options}
      getOptionLabel={(u) => `${u.displayName || u.username} (${u.email || u.userId})`}
      isOptionEqualToValue={(a, b) => a.userId === b.userId}
      onInputChange={(_, v) => onInput(v)}
      loading={loading}
      renderInput={(params) => (
        <TextField
          {...params}
          label="Search user"
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
