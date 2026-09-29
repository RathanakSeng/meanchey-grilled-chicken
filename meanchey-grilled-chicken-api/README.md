# Mean Chey Grilled Chicken — API (មាន់អាំងមានជ័យ)

Backend and Telegram bot for the Mean Chey Grilled Chicken system.

**Phase 1** covers authentication (PC password login + Telegram Mini App), user management by role hierarchy, and a generic, extensible permission system. The business features are the **suppliers** and **customers** lists (`/suppliers`, `/customers`; `docs/FEATURES.md` §11) and **production** batches in three steps with autosaved drafts (`/production`; §14).

📄 Detailed docs: [docs/FEATURES.md](docs/FEATURES.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

Stack: Python 3.12 · FastAPI · Pydantic v2 · PostgreSQL 16 · SQLAlchemy 2 (async) + asyncpg · Alembic · argon2 · PyJWT · aiogram 3 · uv · ruff · pytest.

---

## Quick start (Docker)

```bash
cp .env.example .env          # then set JWT_SECRET (and the Telegram settings, see "Telegram setup")
docker compose up --build
```

This starts two services:

| Service | What it does |
|---|---|
| `postgres` | PostgreSQL 16. Also creates a `meanchey_test` database for the test suite. |
| `api` | Runs the startup sequence below, then serves on http://localhost:8000. In the default `BOT_MODE=webhook` it also receives Telegram updates at `/api/telegram/webhook`, so there is no separate bot process. |

The `api` startup sequence is:

1. `alembic upgrade head` (migrations).
2. `python -m app.bootstrap`: syncs the permission registry, seeds the superadmin, and in webhook mode registers the Telegram webhook if needed.
3. Starts uvicorn.

With `TELEGRAM_BOT_TOKEN` set and `BOT_MODE=webhook` (the default), `TELEGRAM_WEBHOOK_URL` and `TELEGRAM_WEBHOOK_SECRET` are **required**: the api refuses to start without valid values. Without a tunnel, use `BOT_MODE=polling` (see below) or `BOT_MODE=off`.

- OpenAPI docs: http://localhost:8000/docs (development only; see `API_DOCS_ENABLED`)
- First login: username `superadmin`, password `superadmin`. The superadmin is **not** forced to change it; change it from *My profile* right away.

> Port 5432 already in use (e.g. a local PostgreSQL)? Set `POSTGRES_HOST_PORT=5433` in `.env` and point `DATABASE_URL` / `TEST_DATABASE_URL` at `localhost:5433`.

## Local development (without Docker for the API)

```bash
uv sync                                   # creates .venv with runtime + dev deps
docker compose up -d postgres             # or use your own PostgreSQL 16
uv run alembic upgrade head
uv run uvicorn app.main:app --reload      # registry sync + seed (+ webhook registration) on startup
uv run python -m app.bot                  # only with BOT_MODE=polling, in another terminal
```

Quality checks:

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest
```

The tests need PostgreSQL. `TEST_DATABASE_URL` (from the environment or `.env`) must point to a **dedicated** database, because the suite drops and recreates its `public` schema on every run. The schema is built from the Alembic migrations, so the migrations are tested too.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `ENVIRONMENT` | `development` | Set `production` in production. |
| `API_DOCS_ENABLED` | unset | Force `/docs`, `/redoc`, `/openapi.json` on (`true`) or off (`false`). Unset: on only when `ENVIRONMENT=development`. |
| `DATABASE_URL` | `postgresql+asyncpg://meanchey:meanchey@localhost:5432/meanchey` | Async SQLAlchemy URL. Compose overrides the host to `postgres`. |
| `TEST_DATABASE_URL` | `…/meanchey_test` | Used only by `pytest`. It is wiped on every run. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `meanchey` | Compose postgres credentials. |
| `POSTGRES_HOST_PORT` | `5432` | Host port for the compose postgres. |
| `JWT_SECRET` | — (**required**) | HMAC secret for access tokens. Use 32+ random bytes. |
| `ACCESS_TOKEN_TTL_MINUTES` | `15` | Access token lifetime. |
| `REFRESH_TOKEN_TTL_DAYS` | `7` | Refresh token lifetime. Refresh tokens are stored hashed, rotated on use, and revocable. |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCK_MINUTES` | `5` / `15` | Lockout policy for password login. |
| `SUPERADMIN_INITIAL_PASSWORD` | `superadmin` | Seeded superadmin password. A superadmin self-reset also returns to this value. |
| `TELEGRAM_BOT_TOKEN` | empty | Token from @BotFather. Also used to validate Mini App `initData`. |
| `MINI_APP_URL` | empty | Public **HTTPS** URL of the UI. The bot's "Open app" button uses it. |
| `TELEGRAM_INIT_DATA_MAX_AGE_SECONDS` | `86400` | `initData` older than this is rejected. |
| `BOT_MODE` | `webhook` | `webhook` (the API receives updates at `/api/telegram/webhook`) · `polling` (separate `python -m app.bot`, local dev without a tunnel) · `off` |
| `TELEGRAM_WEBHOOK_URL` | empty | Webhook mode: full public URL, e.g. `https://example.com/api/telegram/webhook`. Must be `https` on port 443, 80, 88 or 8443. Validated at startup. |
| `TELEGRAM_WEBHOOK_SECRET` | empty | Webhook mode: 1–256 chars of `A-Z a-z 0-9 _ -`, checked against Telegram's `X-Telegram-Bot-Api-Secret-Token` header. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `TELEGRAM_WEBHOOK_AUTO_SET` | `true` | Register or refresh the webhook on startup. It is skipped when already up to date. |
| `TELEGRAM_DROP_PENDING_UPDATES` | `false` | Discard updates queued at Telegram when the webhook is (re)registered. |
| `BUSINESS_TIMEZONE` | `Asia/Phnom_Penh` | IANA time zone for business calendars (e.g. "new this month" on suppliers/customers). Validated at startup. |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated. Not needed when the UI proxies `/api`. |

## Roles, scope and permissions

**Role** decides *who* a user may manage. **Permission** decides *what* they may do.

| Role | Count | Created by | Can manage |
|---|---|---|---|
| `superadmin` | exactly 1 (seeded) | seed | general manager, supervisors, staff |
| `general_manager` | 1 active | superadmin | supervisors, staff |
| `supervisor` | many | general manager (or superadmin) | staff |
| `staff` (free-text `position`, e.g. `Grill cook`) | many | GM or supervisor (or superadmin) | nobody (own profile only) |

**Database-level invariants**

- Only one superadmin and one *active* general manager may exist. Both are enforced by partial unique indexes.
- A Telegram username (and a linked Telegram user id) is unique among *active* users. This lets a deactivated account's username be reused.
- `position` is set if and only if the role is `staff`. This is a check constraint. Position is a free-text job title (at most 50 characters) with **no effect on access**.

**Telegram usernames**

- Required for every role except the superadmin, and used as the login username.
- Normalized: the leading `@` is stripped, then lowercased.
- Validated: `[a-z0-9_]{5,32}`.
- `superadmin` is reserved and can't be used as a Telegram username.

**Passwords**

- A new user's initial password is their Telegram username. Every user except the superadmin must change it on first login.
- Until they do, every endpoint except `/auth/me`, `/auth/change-password` and `/auth/logout` returns `403 PASSWORD_CHANGE_REQUIRED`.
- A new password must be at least 8 characters and must not equal the username.

**Password reset** (`users.reset_password`) is available to the superadmin and the general manager only. Its `assignable_to` is `[general_manager]`, so supervisors can never be granted it.

- **Resetting a user in scope** (`POST /users/{id}/reset-password`):
  - The password becomes their Telegram username, and they must change it at next login.
  - All their sessions are revoked, and any lockout is cleared.
- **Resetting yourself** (`POST /me/reset-password`):
  - A GM gets their Telegram username and must change it at next login.
  - The superadmin goes back to `SUPERADMIN_INITIAL_PASSWORD` and is not forced to change it.
  - All of your own sessions are revoked.

**Access levels (what the general manager uses)**

The general manager gives access per feature: **Off**, **View only**, **Record** (production only) or **Full access** (`/users/{id}/features`). Detailed permissions stay underneath and are visible only to the superadmin. See `docs/FEATURES.md` §12.

| Feature | For | View only | Record | Full access | Default |
|---|---|---|---|---|---|
| Suppliers | GM*, supervisor, staff | `suppliers.view` | — | + create, update, delete | supervisor: Full · staff: Off |
| Customers | GM*, supervisor, staff | `customers.view` | — | + create, update, delete | supervisor: Full · staff: Off |
| Production | GM*, supervisor, staff | `production.view` | + create (start batches, fill in and finish steps) | + update (edit finished steps) | supervisor: Full · staff: Off |
| Staff management | GM*, supervisor | `users.view` | — | + create, update | supervisor: Full |

\* For the GM, set by the superadmin only (the GM starts at Full access everywhere).

**General-manager-only permissions** (no feature; managed by the superadmin as detailed permissions): `users.delete` (deactivate / reactivate), `users.reset_password`, `permissions.grant` (set access levels), `production.delete` (cancel production batches). Supervisors never deactivate users and never grant access.

**Defaults**

- The superadmin implicitly holds every permission; these are not stored.
- A new GM gets every `users`, partner and production permission.
- A new supervisor gets every feature at Full access, limited to what their creator holds; staff get everything Off.
- When a release adds a permission with role defaults, existing active users of those roles receive it on the next start (a one-time backfill, audited as `default_backfill`).

**Detailed permissions (superadmin only)**

- `GET /permissions`, `GET /users/{id}/permissions`, `PUT` / `DELETE /users/{id}/permissions/{code}`: anyone else gets `403 FORBIDDEN_ROLE`.
- A permission can only be granted to roles in its `assignable_to`. The `grantable_by` mechanism exists but no permission uses it.
- **Revoking doesn't cascade.** The `permission.revoke` audit entry lists the grants of that permission the user had made to others (`downstream_grants`).

**The superadmin is hidden** from everyone else: references to it read "System", looking it up by id is `404`, and the general manager's audit log leaves out its entries and all detailed-permission entries. See `docs/FEATURES.md` §13.

## Authentication flows

| Endpoint | Notes |
|---|---|
| `POST /api/v1/auth/login` | `{username, password}`. The superadmin logs in with `superadmin`; others with their Telegram username (any case, with or without `@`). 5 failures lock the account for 15 minutes. |
| `POST /api/v1/auth/telegram` | `{init_data}` from `Telegram.WebApp.initData`. See details below. |
| `POST /api/v1/auth/refresh` | Rotates the refresh token: the old one is revoked and a new pair is returned. |
| `POST /api/v1/auth/logout` | Revokes the given refresh token, or all sessions with `all_sessions: true`. |
| `POST /api/v1/auth/change-password` | `{current_password, new_password}` |
| `GET /api/v1/auth/me` | Returns the user, effective permission codes, `manageable_roles`, and `can_self_reset_password`. |

**How `POST /auth/telegram` works**

1. The HMAC is validated with the bot token, following the Telegram docs. Data older than 24 hours is rejected.
2. The user is matched by `telegram_user_id`.
3. If no user is bound to that id yet, the user is matched by normalized Telegram username, and the id is then bound to that user. After binding, only the id is used.
4. If nothing matches, the response is `USER_NOT_REGISTERED`.

The forced password change still applies after a Telegram login.

Deactivated users can't log in, their refresh tokens are revoked, and their existing access tokens stop working immediately, because the user is reloaded on every request.

Errors always look like this:

```json
{ "error": { "code": "MISSING_PERMISSION", "message": "Missing permission", "details": { "required": ["users.create"] } } }
```

The `code` is stable and the UI translates it. Codes are listed in `app/core/errors.py`.

## Endpoints

| Method & path | Guard |
|---|---|
| `PATCH /me` | signed in (name, phone, language) |
| `POST /me/reset-password` | `users.reset_password` (superadmin / GM) |
| `GET /users` | `users.view`, scoped (filters: `role`, `position`, `status`, `q`, paging) |
| `GET /users/positions` | `users.view`, scoped (distinct positions for suggestions) |
| `POST /users` | `users.create`, and the role must be manageable |
| `GET /users/{id}` · `PATCH /users/{id}` | `users.view` · `users.update`, plus scope |
| `POST /users/{id}/role` | Promote / demote (`users.update`). GM: staff ↔ supervisor; superadmin: GM / supervisor / staff. Access resets to the new role's defaults. |
| `POST /users/{id}/deactivate` · `/reactivate` | `users.delete`, plus scope |
| `POST /users/{id}/reset-password` | `users.reset_password`, plus scope |
| `GET /permissions` | signed in (catalog grouped by module) |
| `GET /users/{id}/permissions` | `users.view`, plus scope (`granted` and `can_edit` per permission) |
| `PUT` / `DELETE /users/{id}/permissions/{code}` | `permissions.grant`, plus the grant rules |
| `GET /audit-logs` | superadmin or GM |

Audited actions:

- Authentication: `auth.login`, `auth.login_failed`, `auth.locked`, `auth.logout`, `auth.password_changed`, `auth.telegram_bound`
- User changes: `user.create`, `user.update`, `user.role_change`, `user.deactivate`, `user.reactivate`, `user.password_reset`, `user.password_self_reset`
- Permissions and profile: `permission.grant`, `permission.revoke`, `profile.update`

## Telegram setup

### 1. Create the bot (BotFather)

1. In Telegram, open **@BotFather**, send `/newbot`, and follow the prompts.
2. Copy the token into `.env` as `TELEGRAM_BOT_TOKEN`.
3. Optional: register the Mini App so it opens from the bot profile.
   - `/mybots` → your bot → **Bot Settings** → **Menu Button** → set the URL to your `MINI_APP_URL`.
   - Or use `/newapp` to create a named Mini App.

### 2. Expose the UI over HTTPS (one tunnel for everything)

Telegram only opens Mini Apps over **HTTPS**, and only delivers webhooks over HTTPS. For local testing, tunnel the **UI dev server** (port 5173). The Vite dev server proxies all of `/api` to the API, so the one tunnel URL serves three things:

- the Mini App: `https://<tunnel>/`;
- the JSON API: `https://<tunnel>/api/v1/…`;
- the Telegram webhook: `https://<tunnel>/api/telegram/webhook`.

Use either tool:

```bash
# cloudflared (no account needed for quick tunnels)
cloudflared tunnel --url http://localhost:5173
```

```bash
# or ngrok
ngrok http 5173
```

Then:

1. In `.env`, set:
   ```ini
   MINI_APP_URL=https://<tunnel>
   BOT_MODE=webhook
   TELEGRAM_WEBHOOK_URL=https://<tunnel>/api/telegram/webhook
   TELEGRAM_WEBHOOK_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(32))">
   ```
2. Recreate the api so it reloads `.env` and re-registers the webhook:
   ```bash
   docker compose up -d --force-recreate api
   ```
   A plain `docker compose restart` keeps the old environment.
3. Check the registration:
   ```bash
   docker compose exec api python -m app.bot webhook info
   ```
   It should show your URL, and `-` as the last error.
4. Send `/start` to your bot and tap **Open app**.

**Quick tunnel URLs change on every run.** Each time:

1. Update `MINI_APP_URL` and `TELEGRAM_WEBHOOK_URL`, and the BotFather menu button if you set one.
2. Recreate the api. The webhook is re-set automatically on startup; or run `python -m app.bot webhook set` yourself.

### 3. Without a tunnel: polling mode

For local work where you can't expose HTTPS:

1. Set `BOT_MODE=polling` in `.env`. This applies to the whole stack, so the api won't register a webhook.
2. Run:
   ```bash
   docker compose --profile polling up
   ```
   This adds the `bot-polling` service (`python -m app.bot`). It deletes any existing webhook, then long-polls Telegram.

In polling mode the webhook endpoint returns 404. Only one polling process may run per bot token.

### Webhook CLI

```bash
python -m app.bot webhook info                    # URL, pending updates, last error
python -m app.bot webhook set                     # (re)register from settings
python -m app.bot webhook delete [--drop-pending] # remove it
```

In Docker, prefix these with `docker compose exec api`.

### Bot commands

- `/start`: greets the user in their language, with a hint in the other language, and shows an **Open app** WebApp button.
- `/lang`: toggles the bot language between Khmer and English. For a linked account, it also updates the user's app language.

## Adding a new feature

The permission system is data-driven. A new feature such as "orders" needs no migration for its permissions. It takes three steps:

**1. Registry.** Add the module and permissions in `app/permissions/registry.py`:

```python
MODULES.append(ModuleDef("orders", "Orders", "ការបញ្ជាទិញ"))

PERMISSIONS += [
    PermissionDef(
        code="orders.view",
        module="orders",
        name_en="View orders",
        name_km="មើលការបញ្ជាទិញ",
        description_en="View orders.",
        description_km="មើលការបញ្ជាទិញ។",
        assignable_to=(Role.GENERAL_MANAGER, Role.SUPERVISOR, Role.STAFF),
    ),
]
# Optional: DEFAULT_PERMISSIONS[Role.STAFF] = frozenset({"orders.view"})
```

On the next startup the registry is synced into the `permissions` table. New entries are inserted, names are updated, and entries you remove are marked inactive (never deleted).

**2. Endpoint guard.** Protect the routes:

```python
from app.deps import require_permission


@router.get("/orders")
async def list_orders(user: Annotated[User, Depends(require_permission("orders.view"))]): ...
```

Acting on another user's data? Also call `ensure_can_manage(actor, target)` from `app/permissions/hierarchy.py`. Role-only screens can use `require_role(...)`.

**3. UI.** In `meanchey-grilled-chicken-ui`:

- Add a route wrapped in `<RequireAccess permission="orders.view">`.
- Add a menu entry with `permission: "orders.view"` in `src/layouts/nav.ts`.
- Wrap buttons in `<Can permission="orders.create">`.
- Add translations to both `km.json` and `en.json`.

The new permission shows up automatically in each user's **Permissions** tab, grouped by module, in both languages.

(Your business tables still need their own Alembic migration. Generate one with `uv run alembic revision --autogenerate -m "orders"`.)

## Project layout

```
app/
  main.py            FastAPI app, lifespan (bootstrap), error handlers
  config.py          pydantic-settings
  db.py              async engine / session
  bootstrap.py       registry sync + superadmin seed (idempotent, advisory-locked)
  deps.py            CurrentUser, require_permission, require_role
  core/              errors (codes), security (argon2, JWT), telegram_auth, usernames
  models/            SQLAlchemy models
  schemas/           Pydantic request/response models
  permissions/       registry, sync, hierarchy (scope), service (grants, effective perms)
  services/          auth, users, audit
  api/               routers: auth, me, users, permissions, audit
  bot/               aiogram bot: webhook endpoint + registration, shared setup, handlers, CLI (python -m app.bot)
alembic/             migrations
tests/               pytest suite (scope matrix, grants, defaults, constraints, auth, lockout, Telegram, …)
```
