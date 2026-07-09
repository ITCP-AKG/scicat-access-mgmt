# SciCat Access Management — Frontend

React 18 + Vite + MUI single-page admin app for the access-management backend. Provides
the GUI areas: Groups, Users, Resource Grants, Expiry, Transfers, and Audit — plus an
in-app HTML user manual.

## Stack

React 18 · TypeScript · Vite 5 · MUI v5 + `@mui/x-data-grid` · React Router · TanStack Query.

## Layout

```
src/
  main.tsx, App.tsx      # router (sub-path aware), MUI theme, nav shell
  api/                   # typed client (client.ts) + endpoints.ts + types.ts
  auth/                  # SciCat login + session (useMe) + route guard
  components/            # UserPicker, TemporalWindowField
  pages/                 # GroupsPage, GroupDetailPage, UserGroupsPage,
                         # ResourceGrantsPage, ExpiryDashboard, TransferRulesPage, AuditPage
public/
  manual.html            # standalone user manual (linked as "User Manual" in the nav)
```

## Run locally

```bash
npm install
npm run dev          # http://localhost:5174
```

The Vite dev server proxies API calls so no CORS setup is needed:

| Path | Proxied to (`env` override) |
|------|------------------------------|
| `/api/v1` | `VITE_BACKEND_TARGET` (default `http://localhost:3100`) |
| `/api/v3` | `VITE_SCICAT_TARGET` (default `http://localhost:80`) — SciCat login |

## Build & lint

```bash
npm run build        # tsc + vite build -> dist/
npx tsc --noEmit     # type-check only
npx eslint "src/**/*.{ts,tsx}"
```

## Sub-path / production serving

The app can be served from a sub-path (production serves it under `/access-mgmt`):

| Build env | Purpose |
|-----------|---------|
| `VITE_BASE_PATH` | Vite `base` (e.g. `/access-mgmt/`); sets asset URLs + React Router basename |
| `VITE_BACKEND_BASE` | Prefix prepended to backend calls (e.g. `/access-mgmt`); Traefik strips it back to `/api/v1` |

SciCat login (`/api/v3/auth/login`) is always called at the host root, so it resolves to
SciCat on the same host. With both unset the app serves at `/` against a same-origin backend
(the dev default).

```bash
# production build for the /access-mgmt sub-path
VITE_BASE_PATH=/access-mgmt/ VITE_BACKEND_BASE=/access-mgmt npm run build
```

## User manual

`public/manual.html` is a self-contained styled HTML manual covering every screen and
action with examples. It is reachable in the app via the **User Manual** nav link
(`<base>/manual.html`) and can be opened/printed directly.

## Deployment

Wired into both `../../dev-environment/docker-compose.yaml` (Vite HMR on 5174) and
`../../deployment/docker-compose.yaml` (built and served by nginx behind Traefik under
`/access-mgmt`). See `../backend/README.md` for the API and env.
