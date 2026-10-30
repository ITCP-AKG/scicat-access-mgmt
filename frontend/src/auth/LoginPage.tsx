import { useState, type FormEvent } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { useAuth } from './AuthContext';

export default function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username, password);
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
            University (KIT) users: sign in to catorga in this browser; that session is used
            here automatically. The form below is for SciCat functional accounts only.
          </Typography>
          <form onSubmit={onSubmit}>
            <Stack spacing={2} mt={2}>
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
