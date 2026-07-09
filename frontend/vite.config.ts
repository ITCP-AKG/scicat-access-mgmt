import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The backend serves /api/v1; SciCat login is proxied to the SciCat gateway.
// `base` lets the app be served under a sub-path in production (e.g. /access-mgmt/);
// it defaults to '/' for local dev.
export default defineConfig({
  base: process.env.VITE_BASE_PATH || '/',
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      '/api/v1': {
        target: process.env.VITE_BACKEND_TARGET || 'http://localhost:3100',
        changeOrigin: true,
      },
      '/api/v3': {
        target: process.env.VITE_SCICAT_TARGET || 'http://localhost:80',
        changeOrigin: true,
      },
    },
  },
});
