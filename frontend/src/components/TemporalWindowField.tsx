import { Stack, TextField } from '@mui/material';

export interface TemporalWindow {
  effectiveFrom: string | null;
  expiresAt: string | null;
}

interface Props {
  value: TemporalWindow;
  onChange: (value: TemporalWindow) => void;
}

// Datetime-local inputs; emits ISO strings (UTC) or null. Used by membership and
// (from US5) grant dialogs.
export default function TemporalWindowField({ value, onChange }: Props) {
  function toIso(local: string): string | null {
    return local ? new Date(local).toISOString() : null;
  }
  function toLocal(iso: string | null): string {
    if (!iso) return '';
    const d = new Date(iso);
    const off = d.getTimezoneOffset();
    return new Date(d.getTime() - off * 60000).toISOString().slice(0, 16);
  }
  return (
    <Stack direction="row" spacing={2}>
      <TextField
        label="Effective from"
        type="datetime-local"
        size="small"
        InputLabelProps={{ shrink: true }}
        value={toLocal(value.effectiveFrom)}
        onChange={(e) => onChange({ ...value, effectiveFrom: toIso(e.target.value) })}
      />
      <TextField
        label="Expires at"
        type="datetime-local"
        size="small"
        InputLabelProps={{ shrink: true }}
        value={toLocal(value.expiresAt)}
        onChange={(e) => onChange({ ...value, expiresAt: toIso(e.target.value) })}
      />
    </Stack>
  );
}
