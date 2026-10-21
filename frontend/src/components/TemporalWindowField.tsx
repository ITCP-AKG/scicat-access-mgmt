import { Stack, TextField } from '@mui/material';
import { windowError, type TemporalWindow } from '../lib/forms';

interface Props {
  value: TemporalWindow;
  onChange: (value: TemporalWindow) => void;
  /** Hide the start field (e.g. when only extending an expiry). */
  expiryOnly?: boolean;
}

// Datetime-local inputs in the browser's timezone; emits ISO strings (UTC) or null.
// Used by membership and grant dialogs.
export default function TemporalWindowField({ value, onChange, expiryOnly = false }: Props) {
  function toIso(local: string): string | null {
    return local ? new Date(local).toISOString() : null;
  }
  function toLocal(iso: string | null): string {
    if (!iso) return '';
    const d = new Date(iso);
    const off = d.getTimezoneOffset();
    return new Date(d.getTime() - off * 60000).toISOString().slice(0, 16);
  }
  const error = windowError(value);
  return (
    <Stack direction="row" spacing={2}>
      {!expiryOnly && (
        <TextField
          label="Effective from"
          type="datetime-local"
          size="small"
          InputLabelProps={{ shrink: true }}
          value={toLocal(value.effectiveFrom)}
          onChange={(e) => onChange({ ...value, effectiveFrom: toIso(e.target.value) })}
        />
      )}
      <TextField
        label="Expires at"
        type="datetime-local"
        size="small"
        InputLabelProps={{ shrink: true }}
        value={toLocal(value.expiresAt)}
        onChange={(e) => onChange({ ...value, expiresAt: toIso(e.target.value) })}
        error={!!error}
        helperText={error ?? 'Leave empty for no expiry'}
      />
    </Stack>
  );
}
