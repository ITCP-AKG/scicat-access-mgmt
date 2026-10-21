# Integrating FeLS / RegApp SSO (OIDC) with the SciCat installation

This describes how to enable **Single Sign-On via FeLS / RegApp** (the KIT-SCC
identity proxy, `fels.scc.kit.edu`) in the SciCat backend, so that federated
university users are **just-in-time provisioned** in SciCat on their first SSO login.
Once a user has logged in once, they appear in this app's directory and can be
assigned to groups — the **"log in once, then manage"** model.

RegApp is an OIDC↔SAML identity proxy: it exposes **OpenID Connect** endpoints, so
this is an **OIDC** integration. SciCat's backend supports OIDC natively. Unlike the
LDAP path, OIDC *can* map a claim into `accessGroups` — but for this design we keep
that minimal and let **this app stay the source of truth** for groups.

See also [ldap_readme.md](./ldap_readme.md) for the alternative KIT-AD/LDAP path.

## How it fits together

```
Browser ──"Login with SSO"──▶ SciCat  GET /api/v3/auth/oidc
                                   │  redirect
                                   ▼
                         FeLS / RegApp (fels.scc.kit.edu)  ── home-IdP login + 2FA
                                   │  redirect back with code
                                   ▼
        SciCat  GET /api/v3/auth/oidc/callback ── JIT-provisions User + UserIdentity (dacat)
                                   │
                                   ▼
                    appears in THIS app's directory ── you assign groups → projection writes accessGroups
```

A user logs in once via SSO → SciCat creates their `UserIdentity` → they show up in
the group UI → you manage them. RegApp handles authentication (incl. 2FA) and
federation; assigning real `accessGroups` is this app's job, via projection.

## Key differences vs the LDAP path

| | LDAP (KIT-AD) | OIDC (FeLS / RegApp) |
| --- | --- | --- |
| Auth UX | username/password posted to SciCat | browser redirect to SSO |
| **2FA** | no | **yes** (RegApp 2FA) |
| Federation reach | KIT-AD accounts | DFN-AAI / Helmholtz / home IdPs (38k+ users) |
| Dev testing | works on localhost (inside KIT net) | needs a **public HTTPS** callback |
| Group claims | none (static only) | possible, but keep off for this design |
| Prereq from SCC | service/bind account | registered **OIDC client** |

Recommendation: OIDC/FeLS is the better long-term choice (2FA, broader federation,
modern protocol) and still leaves this app as the group source of truth. The main
cost is needing a public HTTPS endpoint to test the redirect flow, which LDAP avoids.

## Step 1 — Register an OIDC client (Relying Party) in RegApp / FeLS

Via the RegApp portal / SCC, register SciCat as an OIDC client. You receive:

- **`client_id`** and **`client_secret`**
- the **issuer / discovery URL** (the `.../.well-known/openid-configuration` base) —
  RegApp publishes the OIDC endpoints; get the exact issuer from them, do **not** guess it.
- you must register your **redirect URI** = `<SciCat public URL>/api/v3/auth/oidc/callback`.

Decide which **scopes/claims** carry identity (and optionally group/entitlement
info): typically `openid profile email`, plus an `eduperson_entitlement`/groups
claim only if you ever want IdP-driven groups.

## Step 2 — Reachability + HTTPS reality check

OIDC redirects a **browser**, so:

- `OIDC_CALLBACK_URL` **must be a publicly reachable HTTPS URL** that RegApp can
  redirect back to, and it must **exactly match** the redirect URI you registered.
- A pure `http://localhost:80` dev stack generally **won't** work for SSO — you need
  a public hostname + TLS (or a tunnel) for testing. (LDAP can be tested locally
  inside the KIT network; OIDC cannot.)

## Step 3 — Add OIDC config to `dev-environment/config/backend/config.env`

Exact variables read by the image `ghcr.io/scicatproject/backend-next:v4.3.1`
(`SciCatProject/scicat-backend-next@v4.3.1`, `src/config/configuration.ts`):

```bash
# --- OIDC / FeLS (RegApp) ---
OIDC_ISSUER=<issuer URL from RegApp, e.g. https://fels.scc.kit.edu/...>   # CONFIRM with SCC
OIDC_CLIENT_ID=<from RegApp client registration>
OIDC_CLIENT_SECRET=<from RegApp client registration>
OIDC_CALLBACK_URL=https://<your-scicat-host>/api/v3/auth/oidc/callback
OIDC_SCOPE=openid profile email
OIDC_SUCCESS_URL=https://<your-scicat-frontend>/        # where to land after login
OIDC_RETURN_URL=https://<your-scicat-frontend>/
OIDC_AUTO_LOGOUT=false

# Keep this app as the source of truth for groups — don't let the IdP drive accessGroups:
# OIDC_ACCESS_GROUPS=...            # leave unset / minimal
# OIDC_ACCESS_GROUPS_PROPERTY=...   # only set if you WANT a claim mapped to accessGroups
```

Values **only RegApp / SCC can provide**: `OIDC_ISSUER`, `OIDC_CLIENT_ID`,
`OIDC_CLIENT_SECRET`, and the registered redirect URI. Everything else is fixed by
the SciCat source + your hostnames.

### Env variable reference (v4.3.1)

| Setting | Variable | Notes |
| --- | --- | --- |
| Issuer | `OIDC_ISSUER` | discovery base, from RegApp |
| Client ID | `OIDC_CLIENT_ID` | from RegApp |
| Client secret | `OIDC_CLIENT_SECRET` | from RegApp |
| Callback URL | `OIDC_CALLBACK_URL` | must equal registered redirect URI |
| Scope | `OIDC_SCOPE` | e.g. `openid profile email` |
| Post-login URL | `OIDC_SUCCESS_URL` | frontend landing |
| Return URL | `OIDC_RETURN_URL` | post-flow redirect |
| Auto logout | `OIDC_AUTO_LOGOUT` | |
| Group claim mode | `OIDC_ACCESS_GROUPS` | leave minimal for this design |
| Group claim field | `OIDC_ACCESS_GROUPS_PROPERTY` | only if mapping a claim → groups |

Related access-group variables that exist in this image (for reference):
`ACCESS_GROUPS_STATIC_VALUES`, `ACCESS_GROUP_SERVICE_TOKEN`,
`ACCESS_GROUP_SERVICE_API_URL`, `ADMIN_GROUPS`, `DELETE_GROUPS`,
`CREATE_DATASET_GROUPS`.

## Step 4 — Show the SSO button on the SciCat frontend

OIDC isn't a username/password form, so the SciCat web UI needs a login entry that
links to `GET /api/v3/auth/oidc`. This is configured in
`dev-environment/config/frontend/config.json` via the `oAuth2Endpoints` array (empty
by default). Add an entry pointing `authURL` at the OIDC initiation route, e.g.:

```json
"oAuth2Endpoints": [
  {
    "displayText": "Login with FeLS (SSO)",
    "authURL": "/api/v3/auth/oidc"
  }
]
```

Note: this is **only** for the SciCat web UI. This access-mgmt app does not need it —
it just consumes the resulting SciCat JWT. (Confirm the exact accepted keys against
your installed frontend version if the button doesn't render.)

## Step 5 — Restart and test (in a browser)

```bash
cd ../dev-environment
docker compose up -d scicat-backend scicat-frontend
```

Then open `https://<your-scicat-host>/api/v3/auth/oidc` in a browser → you should be
redirected to FeLS, authenticate (incl. 2FA), and land back via the callback with a
SciCat session/JWT. On first success a `UserIdentity` row is created.

## Step 6 — Confirm it landed in this app

```bash
# directly in Mongo:
docker exec -it <mongo> mongosh dacat --eval 'db.UserIdentity.find({},{ "profile.username":1 })'

# or via this app's directory search (with an admin Bearer token):
GET http://localhost:3100/api/v1/users?q=<name>
```

The new user should now be assignable to groups; a `Project now` then stamps their
`accessGroups`.

## Caveats

1. **New SSO users start with no real groups** — only `ACCESS_GROUPS_STATIC_VALUES`
   (if set) or a mapped claim (if you enable `OIDC_ACCESS_GROUPS_PROPERTY`). By
   design, this app is the source of truth for groups and fills that gap; keep the
   IdP-driven mapping off unless you have a specific reason.
2. **Public HTTPS callback required** — the redirect flow can't be exercised against
   `http://localhost`. Use a public hostname + TLS or a tunnel for testing.
3. **`userId` matching** — projection matches on `userId` / `profile.id`. After the
   first real login, verify the value this app stores as `userId` matches what
   SciCat's OIDC provisioning writes, so projection targets the right row.

## Sources

- KIT SCC — RegApp / AAI (FeLS): https://fels.scc.kit.edu
- RegApp documentation: https://gitlab.kit.edu/groups/kit/reg-app/-/wikis/home
- SciCat backend config: `SciCatProject/scicat-backend-next@v4.3.1`
  (`src/config/configuration.ts`, `src/auth/auth.controller.ts`)
