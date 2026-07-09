# Implementation Plan: SciCat Access Management

**Branch**: `001-scicat-access-mgmt` | **Date**: 2026-06-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-scicat-access-mgmt/spec.md`

## Summary

A dedicated full-stack administrative application that becomes the **source of truth** for SciCat access groups and membership — capabilities SciCat itself lacks. A FastAPI + MongoDB backend stores first-class Groups, Memberships (with temporal windows), Resource Grants, Transfer Rules, and an Audit log; a projection/sync engine computes each user's effective access groups and writes them into SciCat's `UserIdentity.profile.accessGroups`, and stamps `ownerGroup`/`accessGroups` onto SciCat resources via the SciCat REST API. A scheduler enforces expirations and runs automatic ownership transfers. A React 18 + Vite + MUI frontend (matching the existing `catorga_frontend` stack) provides the admin GUI. Administrators authenticate with their SciCat JWT; app actions are restricted to SciCat admins and app-managed group managers.

## Technical Context

**Language/Version**: Backend — Python 3.11 (FastAPI). Frontend — TypeScript 5.2 / React 18.2.

**Primary Dependencies**:
- Backend: FastAPI, Uvicorn, Pydantic v2, Motor (async MongoDB driver), `httpx` (SciCat REST client), APScheduler (in-process scheduler), PyJWT (validate SciCat JWT), `python-jose`/`passlib` not required.
- Frontend: React 18.2, Vite 5, MUI v5 (`@mui/material`, `@mui/icons-material`), `@mui/x-data-grid` v6, `@emotion/react`/`@emotion/styled`, React Router, TanStack Query (server-state/caching) — kept consistent with `catorga_frontend` where possible.

**Storage**:
- App store: a dedicated MongoDB database `scicat_access_mgmt` on the existing Mongo instance (collections: `groups`, `memberships`, `resource_grants`, `transfer_rules`, `transfer_records`, `audit_log`, `sync_state`).
- Projection target: SciCat's own MongoDB database `dacat`, collection `UserIdentity` (field `profile.accessGroups`) — written directly because SciCat exposes no REST write path for identities. Resource group fields are written via the SciCat REST API, not Mongo.

**Testing**: Backend — `pytest` + `pytest-asyncio` + `httpx` test client + `mongomock-motor`/ephemeral Mongo for integration. Frontend — Jest + Testing Library (matching `catorga_frontend`).

**Target Platform**: Linux containers, orchestrated by the existing `dev-environment/docker-compose.yaml` (Traefik reverse proxy, shared Mongo). Browser (evergreen) for the SPA.

**Project Type**: Web application (separate backend + frontend) living in this repo (`scicat-access-mgmt`).

**Performance Goals**: On-demand projection for a single user < 1 s (SC-002). Full reconciliation of the lab's user base (hundreds of users) within one scheduled cycle. Bulk grant over 100+ resources with per-item result reporting (SC-006). Scheduler tick (expiry sweep) at a configurable interval (default 5 min) idempotent and well under the interval.

**Constraints**: Must not corrupt either store on partial failure — projection/transfer are idempotent and reconcilable (SC-008). SciCat may be temporarily unreachable; intended state is preserved for retry. Direct writes to SciCat's `UserIdentity` are confined to the `profile.accessGroups` field and are computed deterministically from app state, never hand-merged. All temporal boundaries evaluated in one canonical timezone (UTC) and stored as UTC instants.

**Scale/Scope**: Single SciCat instance. Order of tens of groups, hundreds of users, thousands of resources. ~7 GUI areas (groups, membership, resource grants, expiry dashboard, transfer rules, audit, login/shell).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The project constitution (`.specify/memory/constitution.md`) is the unpopulated template with no ratified principles, so there are no explicit gates to enforce. Applying sensible defaults consistent with the existing catorga projects:

- **Separation of concerns**: backend owns persistence + sync; frontend is presentation only. ✅ honored by the structure below.
- **Testability**: services and the sync engine are pure/injectable (SciCat client and clock injected) so they can be unit-tested without a live SciCat. ✅
- **No silent data loss**: every projection/transfer is reconcilable and audited. ✅ (FR-013, FR-021, FR-022).
- **Reuse existing stack**: frontend mirrors `catorga_frontend` (React/Vite/MUI); backend mirrors the `scicat-catalysis-addon` FastAPI conventions. ✅

No violations → Complexity Tracking left empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-scicat-access-mgmt/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (REST API contract)
│   └── openapi.yaml
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── main.py                  # FastAPI app factory, router mount, scheduler startup
│   ├── config.py                # Settings (Mongo URIs, SciCat base URL, JWT secret, intervals, reserved groups)
│   ├── db.py                    # Motor clients: app DB + SciCat (dacat) DB
│   ├── auth/
│   │   ├── jwt.py               # Validate SciCat JWT, extract identity
│   │   └── deps.py              # FastAPI deps: current_user, require_admin, require_group_manager
│   ├── models/                  # Pydantic domain + DB models
│   │   ├── group.py
│   │   ├── membership.py
│   │   ├── resource_grant.py
│   │   ├── transfer.py          # TransferRule, TransferRecord
│   │   ├── audit.py
│   │   └── directory.py         # DirectoryUser
│   ├── services/
│   │   ├── groups.py            # Group CRUD + reserved-name validation
│   │   ├── memberships.py       # Membership CRUD, status computation
│   │   ├── grants.py            # Resource grant apply/remove (bulk)
│   │   ├── projection.py        # Compute effective accessGroups + write to SciCat UserIdentity
│   │   ├── reconcile.py         # Drift detection + full reconciliation
│   │   ├── transfers.py         # Transfer-rule matching + ownership reassignment (idempotent)
│   │   ├── audit.py             # Append-only audit writer + query
│   │   ├── scicat_client.py     # httpx client: resources PATCH, whoami, counts
│   │   └── directory/
│   │       ├── base.py          # DirectoryProvider protocol (search/list/get/deactivated?)
│   │       └── scicat_local.py  # Reads SciCat UserIdentity (Mongo) — the v1 provider
│   ├── scheduler/
│   │   └── jobs.py              # APScheduler: expiry sweep, periodic reconcile, transfer sweep
│   └── api/
│       ├── router.py            # aggregates routers under /api/v1
│       ├── groups.py
│       ├── memberships.py
│       ├── users.py             # directory search + a user's groups + deactivate
│       ├── grants.py            # resource grant endpoints (typed + bulk)
│       ├── projection.py        # trigger projection / reconcile, get sync status
│       ├── transfers.py         # transfer rules CRUD + records
│       ├── audit.py
│       └── expiry.py            # expiry dashboard (upcoming/expired)
├── tests/
│   ├── unit/                    # services with injected clock + fake SciCat client
│   ├── integration/             # API + ephemeral Mongo + mock SciCat
│   └── conftest.py
├── pyproject.toml
└── Dockerfile

frontend/
├── src/
│   ├── main.tsx, App.tsx        # router + MUI theme + query client + auth guard
│   ├── api/                     # typed client for backend /api/v1 + SciCat login
│   ├── auth/                    # SciCat login, token storage, role context
│   ├── components/              # shared: DataGrid wrappers, dialogs, TemporalWindowField, UserPicker
│   └── pages/
│       ├── GroupsPage.tsx       # list + detail
│       ├── GroupDetailPage.tsx  # members editor + applied grants
│       ├── MembershipEditor.tsx
│       ├── ResourceGrantsPage.tsx   # typed resource browse + bulk apply
│       ├── ExpiryDashboard.tsx
│       ├── TransferRulesPage.tsx
│       └── AuditPage.tsx
├── tests/
├── index.html, vite.config.ts, tsconfig.json, package.json
└── Dockerfile

# Integration: add backend + frontend services to ../dev-environment/docker-compose.yaml
# (backend reaches mongodb + scicat-backend; frontend served via Traefik path or its own port)
```

**Structure Decision**: Web application with separate `backend/` (FastAPI) and `frontend/` (React/Vite) at the repo root, mirroring the conventions already established by `scicat-catalysis-addon` (FastAPI: `app/api`, `app/services`, `app/models`) and `catorga_frontend` (React/Vite/MUI: `src/pages`, `src/components`, `src/api`). The backend owns all persistence and the SciCat sync; the frontend is a thin SPA against the backend's `/api/v1`. The directory layer is a provider protocol with a single `scicat_local` implementation today, leaving an obvious seam for a future LDAP/AD provider.

## Complexity Tracking

> No constitution violations to justify — section intentionally empty.
