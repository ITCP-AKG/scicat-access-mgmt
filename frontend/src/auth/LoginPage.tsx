import { useState, type FormEvent } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import type { LoginMethod } from '../api/client';
import { useAuth } from './AuthContext';

export default function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [method, setMethod] = useState<LoginMethod>('local');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username, password, method);
    } catch {
      setError('Login failed. Check your SciCat credentials.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box display="flex" justifyContent="center" alignItems="center" minHeight="100vh">
      <Card sx={{ width: 380 }}>
        <CardContent>
          <Typography variant="h5" gutterBottom>
            SciCat Access Management
          </Typography>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            Sign in with your university account, or a SciCat functional account. If you
            are signed in to catorga in this browser, that session is used automatically.
          </Typography>
          <form onSubmit={onSubmit}>
            <Stack spacing={2} mt={2}>
              <ToggleButtonGroup
                exclusive
                size="small"
                value={method}
                onChange={(_, v: LoginMethod | null) => v && setMethod(v)}
              >
                <ToggleButton value="ldap">University (LDAP)</ToggleButton>
                <ToggleButton value="local">SciCat account</ToggleButton>
              </ToggleButtonGroup>
              {error && <Alert severity="error">{error}</Alert>}
              <TextField
                label="Username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
                fullWidth
              />
              <TextField
                label="Password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                fullWidth
              />
              <Button type="submit" variant="contained" disabled={busy || !username}>
                {busy ? 'Signing in…' : 'Sign in'}
              </Button>
            </Stack>
          </form>
        </CardContent>
      </Card>
    </Box>
  );
}
