import {
  AppBar,
  Box,
  Button,
  CircularProgress,
  Drawer,
  List,
  ListItemButton,
  ListItemText,
  Toolbar,
  Typography,
} from '@mui/material';
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from './auth/AuthContext';
import LoginPage from './auth/LoginPage';
import GroupsPage from './pages/GroupsPage';
import GroupDetailPage from './pages/GroupDetailPage';
import UserGroupsPage from './pages/UserGroupsPage';
import ResourceGrantsPage from './pages/ResourceGrantsPage';
import ExpiryDashboard from './pages/ExpiryDashboard';
import TransferRulesPage from './pages/TransferRulesPage';
import AuditPage from './pages/AuditPage';
import type { Me } from './api/types';

const DRAWER_WIDTH = 220;

type Role = 'any' | 'manager' | 'admin';

// Mirrors the backend: managers (of any group) see directory, grants and expiry views;
// transfers and the audit log are admin-only.
const NAV: { to: string; label: string; role: Role }[] = [
  { to: '/groups', label: 'Groups', role: 'any' },
  { to: '/users', label: 'Users', role: 'manager' },
  { to: '/grants', label: 'Resource Grants', role: 'manager' },
  { to: '/expiry', label: 'Expiry', role: 'manager' },
  { to: '/transfers', label: 'Transfers', role: 'admin' },
  { to: '/audit', label: 'Audit', role: 'admin' },
];

function allowed(role: Role, me: Me | null): boolean {
  if (!me) return false;
  if (role === 'admin') return me.isAdmin;
  if (role === 'manager') return me.isAdmin || me.managerOf.length > 0;
  return true;
}

function Shell({ children }: { children: React.ReactNode }) {
  const { me, logout } = useAuth();
  const location = useLocation();
  return (
    <Box sx={{ display: 'flex' }}>
      <AppBar position="fixed" sx={{ zIndex: (t) => t.zIndex.drawer + 1 }}>
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            SciCat Access Management
          </Typography>
          <Typography variant="body2" sx={{ mr: 2 }}>
            {me?.username}{' '}
            {me?.isAdmin ? '(admin)' : me?.managerOf.length ? `(manager of ${me.managerOf.length})` : ''}
          </Typography>
          <Button color="inherit" onClick={logout}>
            Sign out
          </Button>
        </Toolbar>
      </AppBar>
      <Drawer
        variant="permanent"
        sx={{
          width: DRAWER_WIDTH,
          flexShrink: 0,
          [`& .MuiDrawer-paper`]: { width: DRAWER_WIDTH, boxSizing: 'border-box' },
        }}
      >
        <Toolbar />
        <List>
          {NAV.filter((item) => allowed(item.role, me)).map((item) => (
            <ListItemButton
              key={item.to}
              component={Link}
              to={item.to}
              selected={location.pathname.startsWith(item.to)}
            >
              <ListItemText primary={item.label} />
            </ListItemButton>
          ))}
          <ListItemButton
            component="a"
            href={`${import.meta.env.BASE_URL}manual.html`}
            target="_blank"
            rel="noopener"
          >
            <ListItemText primary="User Manual" />
          </ListItemButton>
        </List>
      </Drawer>
      <Box component="main" sx={{ flexGrow: 1, p: 3 }}>
        <Toolbar />
        {children}
      </Box>
    </Box>
  );
}

export default function App() {
  const { me, loading } = useAuth();

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="100vh">
        <CircularProgress />
      </Box>
    );
  }

  if (!me) return <LoginPage />;

  return (
    <Shell>
      <Routes>
        <Route path="/groups" element={<GroupsPage />} />
        <Route path="/groups/:name" element={<GroupDetailPage />} />
        {allowed('manager', me) && <Route path="/users" element={<UserGroupsPage />} />}
        {allowed('manager', me) && <Route path="/grants" element={<ResourceGrantsPage />} />}
        {allowed('manager', me) && <Route path="/expiry" element={<ExpiryDashboard />} />}
        {allowed('admin', me) && <Route path="/transfers" element={<TransferRulesPage />} />}
        {allowed('admin', me) && <Route path="/audit" element={<AuditPage />} />}
        <Route path="*" element={<Navigate to="/groups" replace />} />
      </Routes>
    </Shell>
  );
}
