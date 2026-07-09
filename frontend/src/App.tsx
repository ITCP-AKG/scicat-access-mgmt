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

const DRAWER_WIDTH = 220;

const NAV = [
  { to: '/groups', label: 'Groups' },
  { to: '/users', label: 'Users' },
  { to: '/grants', label: 'Resource Grants' },
  { to: '/expiry', label: 'Expiry' },
  { to: '/transfers', label: 'Transfers' },
  { to: '/audit', label: 'Audit' },
];

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
            {me?.username} {me?.isAdmin ? '(admin)' : ''}
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
          {NAV.map((item) => (
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
        <Route path="/users" element={<UserGroupsPage />} />
        <Route path="/grants" element={<ResourceGrantsPage />} />
        <Route path="/expiry" element={<ExpiryDashboard />} />
        <Route path="/transfers" element={<TransferRulesPage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="*" element={<Navigate to="/groups" replace />} />
      </Routes>
    </Shell>
  );
}
