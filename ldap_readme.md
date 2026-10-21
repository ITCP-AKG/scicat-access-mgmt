# Integrating KIT-AD (LDAP) with the SciCat installation

This describes how to enable LDAP authentication against **KIT-AD** in the SciCat
backend so that real university users are **just-in-time provisioned** in SciCat on
their first login. Once a user has logged in once, they appear in this app's
directory and can be assigned to groups — the **"log in once, then manage"** model.

This app stays a pure consumer of SciCat's `UserIdentity`; it does **not** scan the
LDAP directory in advance.

## How it fits together

```
KIT-AD (kit-ad.scc.kit.edu)
   │  POST /api/v3/auth/ldap {username,password}
   ▼
SciCat backend  ── authenticates + JIT-provisions ──▶ creates User + UserIdentity (dacat)
   │                                                           │
   │   (LDAP path sets NO real accessGroups — only static)     ▼
   └────────────────────────────────────────────▶  appears in THIS app's directory
                                                              │
                                          you assign groups → projection writes accessGroups
```

A user logs in once → SciCat creates their `UserIdentity` → they show up in the
group UI → you manage them. SciCat's LDAP path handles **authentication + JIT
provisioning only**; it does **not** map LDAP groups to `accessGroups` (only
`ACCESS_GROUPS_STATIC_VALUES` / the OIDC path do). Assigning real `accessGroups` is
this app's job, via projection.

## KIT-AD connection facts (from SCC docs)

- Server: `kit-ad.scc.kit.edu` (load-balanced proxy in front of KIT-AD domain controllers).
- TLS is **mandatory** (TLS or STARTTLS). Port constellations forwarded 1:1:
  - LDAPS (TLS) on **636** → Domain Partition
  - LDAPS (TLS) on **3269** → Global Catalog
  - STARTTLS on **389** → Domain Partition
  - STARTTLS on **3268** → Global Catalog
- Reachable **only from inside the KIT network** (VPN if remote).
- An **authenticated bind is required** even to search (no anonymous bind).
- Search objects via their **CN**, not via a static DN (AD contents are dynamic).

## Step 1 — Get a KIT service account (do this first; it's the blocker)

KIT-AD requires an authenticated bind to search, and SciCat does search-then-bind,
so you need a **Funktionskonto / service account** from SCC for `LDAP_BIND_DN` /
`LDAP_BIND_CREDENTIALS`. It only needs read access to the directory.

## Step 2 — Network + TLS reality check

- The SciCat container's host must be on the **KIT network / VPN** — a laptop dev
  stack won't reach KIT-AD otherwise.
- Use **LDAPS on 636** (simplest): `ldaps://kit-ad.scc.kit.edu:636`.
- The `backend-next` v4.3.1 config exposes no TLS/CA options, so it relies on Node
  trusting KIT's CA. KIT-AD certs are typically DFN/Sectigo (public) → trusted out
  of the box. If you hit a cert error, mount the CA into the `scicat-backend`
  container and set `NODE_EXTRA_CA_CERTS` to its path.

## Step 3 — Add LDAP config to `dev-environment/config/backend/config.env`

These are the exact environment variables read by the image
`ghcr.io/scicatproject/backend-next:v4.3.1`
(`SciCatProject/scicat-backend-next@v4.3.1`, `src/config/configuration.ts`):

```bash
# --- LDAP / KIT-AD ---
LDAP_URL=ldaps://kit-ad.scc.kit.edu:636
LDAP_BIND_DN=<service account, e.g. svc-scicat@kit.edu or its full CN=...,DC=kit,DC=edu>
LDAP_BIND_CREDENTIALS=<service-account-password>
LDAP_SEARCH_BASE=<your base DN, e.g. DC=kit,DC=edu>     # CONFIRM with SCC
LDAP_SEARCH_FILTER=(sAMAccountName={{username}})
# Defaults below are already correct for AD — set explicitly only if you want:
LDAP_MODE=ad
LDAP_EXTERNAL_ID=sAMAccountName
LDAP_USERNAME=displayName
```

Two values **must be confirmed with SCC** — they can't be inferred:

- `LDAP_SEARCH_BASE` — your exact AD domain / OU base DN.
- the bind account (`LDAP_BIND_DN` / `LDAP_BIND_CREDENTIALS`).

Everything else above is fixed by KIT's docs and the SciCat source.

### Env variable reference (v4.3.1)

| Setting               | Variable                | Default          |
| --------------------- | ----------------------- | ---------------- |
| Server URL            | `LDAP_URL`              | —                |
| Bind DN               | `LDAP_BIND_DN`          | —                |
| Bind credentials      | `LDAP_BIND_CREDENTIALS` | —                |
| Search base           | `LDAP_SEARCH_BASE`      | —                |
| Search filter         | `LDAP_SEARCH_FILTER`    | —                |
| Mode                  | `LDAP_MODE`             | `ad`             |
| External ID attribute | `LDAP_EXTERNAL_ID`      | `sAMAccountName` |
| Username attribute    | `LDAP_USERNAME`         | `displayName`    |

## Step 4 — Restart and test

```bash
cd ../dev-environment
docker compose up -d scicat-backend     # reloads .env

# Test LDAP auth + JIT provisioning with a real KIT user:
curl -X POST http://localhost:80/api/v3/auth/ldap \
  -H 'Content-Type: application/json' \
  -d '{"username":"<kit-username>","password":"<kit-password>"}'
```

Login route is `POST /auth/ldap` (legacy alias `/auth/msad`); `/auth/login` remains
for the functional accounts. On success a `UserIdentity` row is created.

## Step 5 — Confirm it landed in this app

```bash
# directly in Mongo:
docker exec -it <mongo> mongosh dacat --eval 'db.UserIdentity.find({},{ "profile.username":1 })'

# or via this app's directory search (with an admin Bearer token):
GET http://localhost:3100/api/v1/users?q=<name>
```

The new user should now be assignable to groups; a `Project now` then stamps their
`accessGroups`.

## Caveats

1. **New LDAP users start with no real groups** — only `ACCESS_GROUPS_STATIC_VALUES`
   (if set). By design: this app is the source of truth for groups and fills that gap.
2. **Frontend login form** — the SciCat web UI may need its login config pointed at
   the LDAP endpoint to show it; irrelevant for this app's flow, which only needs the
   JWT (API login works regardless).
3. **`userId` matching** — projection matches on `userId` / `profile.id`. After the
   first real login, verify the value this app stores as `userId` matches what
   SciCat's LDAP provisioning writes, so projection targets the right row.

## Sources

- KIT SCC — "LDAP access to KIT-AD": https://www.scc.kit.edu/en/services/kit-ad-ldap.php
- SciCat backend config: `SciCatProject/scicat-backend-next@v4.3.1`
  (`src/config/configuration.ts`, `src/auth/auth.controller.ts`)
