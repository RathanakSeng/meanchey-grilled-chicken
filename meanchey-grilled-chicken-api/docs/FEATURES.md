# API Features — Phase 1

What the Mean Chey Grilled Chicken API (មាន់អាំងមានជ័យ) does today. Phase 1 covers authentication, user management and access control (feature access levels over detailed permissions, §5 and §12). The business features, **suppliers and customers** (§11) and **production** (§14), plug into the permission system described here, as will later ones (orders, stock, delivery, …).

- [1. Authentication](#1-authentication)
- [2. Password policy](#2-password-policy)
- [3. Roles and hierarchy](#3-roles-and-hierarchy)
- [4. User management](#4-user-management)
- [5. Permission system](#5-permission-system)
- [6. Audit log](#6-audit-log)
- [7. Telegram bot](#7-telegram-bot)
- [8. Internationalization](#8-internationalization)
- [9. Error codes](#9-error-codes)
- [10. Endpoint reference](#10-endpoint-reference)
- [11. Suppliers & customers](#11-suppliers--customers)
- [12. Feature access levels](#12-feature-access-levels)
- [13. Visibility and redaction](#13-visibility-and-redaction)
- [14. Production](#14-production)

---

## 1. Authentication

### 1.1 Password login (PC dashboard)

`POST /api/v1/auth/login` with `{ "username": "...", "password": "..." }`.

| Who | Username |
|---|---|
| Superadmin | `superadmin` |
| Everyone else | Their Telegram username. It is normalized, so `@Sok_Dara`, `sok_dara` and `SOK_DARA` all work. |

It returns:

```json
{
  "access_token": "…",
  "refresh_token": "…",
  "token_type": "bearer",
  "expires_in": 900,
  "must_change_password": true
}
```

### 1.2 Telegram Mini App login

`POST /api/v1/auth/telegram` with `{ "init_data": "<Telegram.WebApp.initData>" }`.

1. The `initData` HMAC is validated with the bot token, following [Telegram's algorithm](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app).
   - Tampered data or a wrong bot → `INVALID_TELEGRAM_DATA`.
2. `auth_date` older than 24 h → `TELEGRAM_DATA_EXPIRED`. The limit is configurable.
3. The user is matched in this order:
   1. by `telegram_user_id`, if one is already bound;
   2. otherwise by normalized Telegram username, among active users with no binding yet. The Telegram user id is then **bound** to that user.
4. After binding, the account matches **only** by id. Renaming the Telegram account doesn't break login, and someone else taking the old username can't log in.
5. No match → `USER_NOT_REGISTERED`. A match on a deactivated user → `ACCOUNT_DISABLED`.

The forced password change still applies after a Telegram login.

### 1.3 Tokens

| Token | Lifetime | Storage | Notes |
|---|---|---|---|
| Access (JWT, HS256) | 15 min | Client only | Carries `sub` (user id), `type=access`, `exp`, `iat`, `jti`. |
| Refresh (opaque, random) | 7 days | Only its **SHA-256 hash** is stored, in `refresh_tokens` | Single use: each refresh rotates it. |

- `POST /auth/refresh` revokes the presented refresh token and returns a new pair.
  - A revoked, expired or unknown token → `INVALID_REFRESH_TOKEN`.
- `POST /auth/logout` revokes the given refresh token. With `all_sessions: true` it revokes every session.
- All of a user's refresh tokens are revoked when they are **deactivated** or have their **password reset**.

### 1.4 Account lockout

- **5** consecutive failed password logins lock the account for **15 minutes** (`ACCOUNT_LOCKED`, HTTP 423, with `details.locked_until`).
- While locked, even the correct password is rejected.
- A successful login resets the counter. An admin password reset also clears the lock.
- Lockout applies to password login only. Telegram login is cryptographically verified and is not locked.

### 1.5 Deactivated accounts

Every authenticated request reloads the user from the database, so deactivation takes effect **immediately**:

- existing access tokens → `401 ACCOUNT_DISABLED`;
- refresh tokens are revoked;
- password login → `403 ACCOUNT_DISABLED`. This is shown only when the password is correct; otherwise the response is `INVALID_CREDENTIALS`, so an attacker can't probe which accounts exist.

---

## 2. Password policy

**Initial password**

- A new user's initial password is their normalized Telegram username.
- The superadmin is seeded with `SUPERADMIN_INITIAL_PASSWORD` (default `superadmin`).

**Forced change on first login**

- Every new user except the superadmin gets `must_change_password = true`.
- Until they change it, **every endpoint except** `GET /auth/me`, `POST /auth/change-password` and `POST /auth/logout` returns `403 PASSWORD_CHANGE_REQUIRED`.

**Rules for a new password**

- At least 8 characters (`PASSWORD_TOO_SHORT`).
- Must not equal the username or Telegram username, compared case-insensitively and ignoring a leading `@` (`PASSWORD_EQUALS_USERNAME`).
- The current password is always required (`WRONG_CURRENT_PASSWORD`).

**Password reset** — allowed for the superadmin and the general manager only:

| Action | Endpoint | Result |
|---|---|---|
| Reset a user in scope | `POST /users/{id}/reset-password` | Password becomes their Telegram username, `must_change_password = true`, all sessions revoked, lock cleared. |
| GM resets self | `POST /me/reset-password` | Password becomes their Telegram username, must change at next login, all sessions revoked. |
| Superadmin resets self | `POST /me/reset-password` | Password becomes `SUPERADMIN_INITIAL_PASSWORD`, **no** forced change, all sessions revoked. |

This is enforced through the `users.reset_password` permission, whose `assignable_to` is `[general_manager]`. Supervisors can never receive it.

---

## 3. Roles and hierarchy

| Role | How many | Created by | Manages |
|---|---|---|---|
| `superadmin` | exactly 1, seeded | bootstrap | general manager, supervisors, staff |
| `general_manager` | 1 **active** | superadmin | supervisors, staff |
| `supervisor` | many | general manager (or superadmin) | staff |
| `staff` | many | GM, supervisor (or superadmin) | nobody |

- **Role decides WHO** a user may act on. **Permissions decide WHAT** they may do.
- Nobody can act on a user at the same or a higher level, including themselves. Users edit themselves through `/me`.
- Changing a user's role is out of scope for Phase 1. Deactivate the user and create a new one.

**Invariants enforced by the database**

| Rule | Mechanism |
|---|---|
| Only one superadmin | Partial unique index `uq_users_single_superadmin` |
| Only one active general manager | Partial unique index `uq_users_single_active_gm` |
| Telegram username unique among active users | Partial unique index `uq_users_active_telegram_username` |
| Telegram user id unique among active users | Partial unique index `uq_users_active_telegram_user_id` |
| `position` set if and only if the role is `staff` | Check `ck_users_position_staff_only` |
| Telegram username required except for the superadmin | Check `ck_users_telegram_username_required` |

**Telegram usernames**

- Normalized: whitespace and a leading `@` are stripped, then lowercased.
- Validated: `^[a-z0-9_]{5,32}$` (`INVALID_TELEGRAM_USERNAME`).
- `superadmin` is reserved.

**Position (staff job title)**

- `position` is a **free-text job title**, for example `Grill cook`, `Cashier` or `អ្នកដឹកជញ្ជូន`.
- It is a **descriptive label only**. It has **no effect on access**: role decides who a user can manage, permissions decide what they can do, and no code branches on the position value.
- It is **required** for staff (`POSITION_REQUIRED`) and **not allowed** for other roles (`POSITION_NOT_ALLOWED`). The check `ck_users_position_staff_only` backs this up.
- Normalized on input: trimmed, with internal whitespace collapsed to a single space. Case and Khmer text are kept exactly as typed.
  - Empty after trimming counts as missing, so it gives `POSITION_REQUIRED` for staff.
  - At most 50 characters; longer gives `VALIDATION_ERROR`.
- Earlier values (`worker`, `driver`) are kept as ordinary text.

---

## 4. User management

| Capability | Permission | Scope check | Notes |
|---|---|---|---|
| List users | `users.view` | Only roles the actor manages | Filters: `role`, `position` (case-insensitive exact match), `status` (`active` / `inactive` / `all`), `q` (name, Telegram, phone, position), paging |
| List positions | `users.view` | Only roles the actor manages | `GET /users/positions`: distinct positions of **active** users in scope, sorted. Distinct is case-insensitive, and the most used spelling is returned. Feeds the UI's suggestions and position filter. |
| View a user | `users.view` | yes | |
| Create a user | `users.create` | Role must be manageable | Default permissions are granted automatically (§5.3) |
| Edit a user | `users.update` | yes | Name, phone, language, position (staff, free text), Telegram username. Changing the username unbinds the Telegram account. |
| Change role (promote / demote) | `users.update` | current **and** new role manageable | `POST /users/{id}/role` `{role, position?}`. The actor must manage both the current and the new role: the **general manager** moves users between **staff and supervisor**; the **superadmin** between **general manager, supervisor and staff**. Supervisors can't change roles, and nobody changes their own. The new role's default access **replaces** the old one (supervisor: every feature Full; staff: every feature Off; general manager: all GM permissions); adjust it afterwards with feature levels. Demoting to staff needs a `position`; promoting clears it (`POSITION_REQUIRED` / `POSITION_NOT_ALLOWED`). Only one active general manager (`GM_ALREADY_EXISTS`). Same role again: no-op. The username, password and Telegram link are kept. |
| Deactivate / reactivate | `users.delete` | yes | Soft delete: `is_active=false`, `deleted_at`. Reactivation re-checks the single-GM and username uniqueness rules. |
| Reset password | `users.reset_password` | yes | §2 |
| Edit own profile | signed in | self | `PATCH /me`: name, phone, language |

---

## 5. Permission system

Access has two layers:

- **Detailed permissions** (this section) are the underlying mechanism. Only the **superadmin** sees and edits them.
- **Feature access levels** (§12) sit on top. The general manager sets *Off / View only / Full access* per feature for supervisors and staff and never sees a permission code.

### 5.1 Registry (code is the source of truth)

Permissions are declared in `app/permissions/registry.py`. Each entry has:

- `code`, `module`
- `name_en`, `name_km`
- `description_en`, `description_km`
- `assignable_to`: the roles that may ever hold it.
- `grantable_by` (optional): for a target role, the only grantor roles that may grant or revoke it. Target roles not listed follow the normal rules (§5.4). **No permission uses it today**; the mechanism is kept for later. A permission with `grantable_by` can't be part of a feature (startup validation), because feature levels don't apply per-permission grant rules.

On every startup the registry is **synced** into the `permissions` table:

- new entries are inserted;
- names, descriptions, `assignable_to` and `grantable_by` are updated;
- entries removed from the registry are marked `is_active = false` and never deleted, so the grant history stays intact.

Inactive permissions are ignored everywhere: effective permissions, catalog, grants.

**Defaults for new permissions are backfilled.** Role defaults (§5.3) are normally applied only when a user is created. So that a newly added feature isn't invisible to every existing manager, the sync also grants each **newly inserted** permission to every **active** user whose role has it in `DEFAULT_PERMISSIONS`:

- the grant is made by the system (`granted_by = NULL`);
- each grant writes a `permission.grant` audit entry with `actor = null` and `details.source = "default_backfill"`;
- it runs once per permission (only codes inserted by this run), inside the bootstrap advisory lock. A later start grants nothing, so a deliberate revoke sticks;
- inactive users and roles without the default get nothing.

### 5.2 Permissions

**Module `users`**

| Code | Meaning | Assignable to | In feature |
|---|---|---|---|
| `users.view` | View users in own scope | GM, supervisor | Staff management |
| `users.create` | Create users in own scope | GM, supervisor | Staff management |
| `users.update` | Edit users in own scope | GM, supervisor | Staff management |
| `users.delete` | Deactivate / reactivate users in own scope | **GM only** | — |
| `users.reset_password` | Reset passwords (others in scope, and self) | GM only | — |
| `permissions.grant` | Set feature access levels (GM); grant / revoke detailed permissions (superadmin only, §5.4) | **GM only** | — |

- **Supervisors never deactivate users and never grant access.** `users.delete` and `permissions.grant` are no longer assignable to supervisors. Rows stored before this change stay in the table but have no effect: effective permissions filter on `assignable_to` at read time (§5.5).
- No `users` permission is assignable to staff.

**Module `partners`** (§11)

| Code | Meaning | Assignable to | In feature |
|---|---|---|---|
| `suppliers.view` | View suppliers and their figures | GM, supervisor, staff | Suppliers |
| `suppliers.create` / `.update` / `.delete` | Add / edit / deactivate suppliers | GM, supervisor, staff | Suppliers |
| `customers.view` | View customers and their figures | GM, supervisor, staff | Customers |
| `customers.create` / `.update` / `.delete` | Add / edit / deactivate customers | GM, supervisor, staff | Customers |

The general manager can give any of these to supervisors **and staff** through feature levels.

**Module `production`** (§14)

| Code | Meaning | Assignable to | In feature (level) |
|---|---|---|---|
| `production.view` | See batches, their steps and figures | GM, supervisor, staff | Production (View only and up) |
| `production.create` | Start batches; save drafts and finish steps | GM, supervisor, staff | Production (Record and up) |
| `production.update` | Reopen a finished step (and every later finished step with it) | GM, supervisor, staff | Production (Full access) |
| `production.delete` | Cancel a batch | **GM only** | — (detailed permission) |

Cancelling batches is a general-manager decision, like deactivating users: `production.delete` is assignable to the GM only and belongs to no feature level. Supervisors or staff granted it before this change keep the row, but it has no effect (read-time `assignable_to` filter, §5.5), and their Production level still reads as *Full access*.

### 5.3 Defaults

| Role | On creation |
|---|---|
| Superadmin | Implicitly holds **every** active permission. Nothing is stored. |
| General manager | All `users` permissions (incl. `users.delete`, `users.reset_password`, `permissions.grant`), all partner permissions and all four `production.*` permissions. |
| Supervisor | Every feature at **Full access**: Suppliers, Customers, Production (view, record, reopen finished steps; not cancel), Staff management (= `users.view/create/update`). Limited to what the creator holds. |
| Staff | Every feature **Off** (no permissions). |

`DEFAULT_PERMISSIONS` for supervisors and staff is computed from the feature levels, so the two can't drift apart. When the production permissions were added, the one-time backfill (§5.1) gave them to existing active general managers and supervisors; staff got nothing.

### 5.4 Detailed grant rules (superadmin only)

`GET /permissions`, `GET /users/{id}/permissions`, `PUT` and `DELETE /users/{id}/permissions/{code}` are guarded by `require_role(superadmin)`. Anyone else gets `403 FORBIDDEN_ROLE` (with no list of allowed roles).

For the superadmin, grant (`PUT`) and revoke (`DELETE`) check, in order:

1. The target is in scope (not the superadmin itself). Otherwise → `FORBIDDEN_SCOPE`.
2. The permission exists and is active. Otherwise → `PERMISSION_NOT_FOUND`.
3. For grants: the target is active → `USER_INACTIVE`, and the target's role is in `assignable_to` → `PERMISSION_NOT_ASSIGNABLE`.

(The full rule list in `permissions.service.block_reason`, including `PERMISSION_NOT_HELD` and `grantable_by` → `PERMISSION_GRANT_RESTRICTED`, still applies; the superadmin holds everything and is exempt from `grantable_by`.)

Grant and revoke are idempotent.

**Revoking doesn't cascade.** When permission *P* is revoked from user *U*, any grants of *P* that *U* made to others (for example through feature levels) stay in place. The `permission.revoke` audit entry lists them in `details.downstream_grants`, and the audit log highlights them for follow-up.

### 5.5 Effective permissions

`GET /auth/me` returns:

- `permissions`: the user's effective codes, meaning active permissions that are granted to them and still assignable to their role. The UI builds menus from them;
- `manageable_roles`, `can_self_reset_password`;
- `can_manage_features`: holds `permissions.grant`, i.e. may set feature levels (the Access tab).

`GET /users/{id}/permissions` (superadmin only) returns every permission assignable to the target's role, grouped by module. Each item has `granted`, `granted_by`, `granted_at`, `can_edit` and `reason` (the error code of the first rule that blocks editing, or `null`).

---

## 6. Audit log

Every security-relevant action writes to `audit_logs` (`actor_id`, `action`, `target_user_id`, `entity_type`, `entity_id`, `details` JSONB, `created_at`). `entity_type` / `entity_id` reference a non-user record (`supplier`, `customer`, `production_batch`); they're null for user and auth actions.

| Area | Actions |
|---|---|
| Authentication | `auth.login` (method: password / telegram), `auth.login_failed` (with reason), `auth.locked`, `auth.logout`, `auth.password_changed`, `auth.telegram_bound` |
| Users | `user.create` (includes default permissions), `user.update` (field diff), `user.role_change` (`from`, `to`, `position_from`, `position_to`, `permissions_added`, `permissions_removed`), `user.deactivate`, `user.reactivate`, `user.password_reset`, `user.password_self_reset` |
| Permissions | `permission.grant` (`details.source = "default_backfill"` and no actor when granted by the startup backfill), `permission.revoke` (includes `downstream_grants`). **Superadmin only.** |
| Access | `feature.set`: one entry per change, `details = {feature, from, to, added, removed}` (`from` may be `custom`). No individual `permission.*` entries are written for it. |
| Suppliers | `supplier.create`, `supplier.update` (field diff), `supplier.deactivate`, `supplier.reactivate`. `details.name` holds the record's name. |
| Customers | `customer.create`, `customer.update` (field diff), `customer.deactivate`, `customer.reactivate`. `details.name` holds the record's name. |
| Production | `production.create`, `production.step_finish` (`step`: 1–3), `production.step_reopen` (`step`, `reopened_steps`: e.g. `[1, 2, 3]`), `production.cancel` (`reason`). `details.code` holds the batch code. **Draft saves are not audited.** |
| Profile | `profile.update` |

`GET /audit-logs` is available to the **superadmin and general manager only** (§13 for what the general manager doesn't see). This is a role check, not a permission. It supports filters (`action`, `actor_id`, `target_user_id`, `entity_type`, `entity_id`, `date_from`, `date_to`) and paging. Each entry includes compact actor and target references, and `entity: {type, id, name}` for supplier / customer / production batch entries (the record's current name, or the batch code, falling back to the logged one).

---

## 7. Telegram bot

By default Telegram delivers updates to the API itself through a **webhook**: `POST /api/telegram/webhook`. No separate bot process is needed.

### 7.1 Modes (`BOT_MODE`)

| Mode | How updates arrive | Webhook endpoint | Use for |
|---|---|---|---|
| `webhook` (default) | Telegram → HTTPS → `/api/telegram/webhook` in the API | active | Production, and local dev with an HTTPS tunnel |
| `polling` | A separate `python -m app.bot` process (compose profile `polling`) long-polls Telegram | `404` | Local dev without a tunnel |
| `off` | None | `404` | Tests, API-only runs |

- **No `TELEGRAM_BOT_TOKEN`:** a warning is logged, the endpoint returns `404`, and no `setWebhook` calls are made.
- **Settings are validated at startup.** In webhook mode with a token, `TELEGRAM_WEBHOOK_URL` must be `https://` on port 443, 80, 88 or 8443, and `TELEGRAM_WEBHOOK_SECRET` must be 1–256 characters of `A-Z a-z 0-9 _ -`. Otherwise startup fails with a clear message.

### 7.2 Webhook endpoint

- Excluded from the OpenAPI docs. It has no JWT or auth dependencies, and a pending password change doesn't affect it.
- It checks the `X-Telegram-Bot-Api-Secret-Token` header against `TELEGRAM_WEBHOOK_SECRET` in constant time.
  - If the header is wrong or missing, it returns `401` without processing the body and logs a warning. The secret is never logged.
- Once the secret is valid, it **always answers `200`**, even if the update is malformed or a handler fails. The error is logged with a traceback, and returning 200 stops Telegram redelivering the same update over and over.
- Each update is handled inline, with its own short-lived database session.

### 7.3 Webhook registration

- **On startup** (webhook mode with `TELEGRAM_WEBHOOK_AUTO_SET=true`), the API makes sure Telegram points at `TELEGRAM_WEBHOOK_URL`.
  - `setWebhook` is only called when something changed: the URL, the allowed update types, the secret, or `TELEGRAM_DROP_PENDING_UPDATES`.
  - Telegram never returns the secret, so a fingerprint of what was last registered is kept in `app_settings`.
  - Registration also sets the bot's command list (`/start`, `/lang`).
- **If Telegram is unreachable,** the error is logged and the API starts anyway.

Manual control:

```bash
python -m app.bot webhook info     # URL, pending update count, last error date/message
python -m app.bot webhook set      # (re)register from settings
python -m app.bot webhook delete   # remove it; --drop-pending discards queued updates
```

In Docker, prefix these with `docker compose exec api`.

### 7.4 Commands

| Command | Behavior |
|---|---|
| `/start` | Greets the user in their language, with a hint in the other language, and shows an **Open app** WebApp button pointing to `MINI_APP_URL`. |
| `/lang` | Toggles the bot language between Khmer and English. If the Telegram account is linked to a user, their app language is updated too. |

- **Which language the bot uses:** the linked user's `language` first, then `bot_prefs`, then Khmer.
- **If `MINI_APP_URL` isn't HTTPS or is empty,** the bot says the app isn't configured instead of showing the button.
- **If `TELEGRAM_BOT_TOKEN` is empty,** the bot is disabled. The webhook endpoint returns 404, and the polling process logs a warning and exits cleanly.
- **Commands behave the same in webhook and polling mode.** Both use the same handlers (`app/bot/setup.py`).

---

## 8. Internationalization

- Users have a `language` (`km` default, or `en`). The UI applies it after login and can change it through `PATCH /me`.
- Permission and module names and descriptions are provided in both languages. The UI chooses which one to show.
- Errors carry a stable machine code plus an English `message`. The UI translates the code (§9).

---

## 9. Error codes

Every error has the same shape:

```json
{ "error": { "code": "FORBIDDEN_SCOPE", "message": "Target user is outside your scope", "details": {} } }
```

| Area | Codes |
|---|---|
| Authentication | `NOT_AUTHENTICATED`, `INVALID_TOKEN`, `TOKEN_EXPIRED`, `INVALID_REFRESH_TOKEN`, `INVALID_CREDENTIALS`, `ACCOUNT_LOCKED`, `ACCOUNT_DISABLED`, `PASSWORD_CHANGE_REQUIRED` |
| Passwords | `WRONG_CURRENT_PASSWORD`, `PASSWORD_TOO_SHORT`, `PASSWORD_EQUALS_USERNAME` |
| Telegram | `TELEGRAM_NOT_CONFIGURED`, `INVALID_TELEGRAM_DATA`, `TELEGRAM_DATA_EXPIRED`, `USER_NOT_REGISTERED` |
| Authorization | `FORBIDDEN_SCOPE`, `FORBIDDEN_ROLE`, `MISSING_PERMISSION`, `PERMISSION_NOT_HELD`, `PERMISSION_NOT_ASSIGNABLE`, `PERMISSION_NOT_FOUND`, `PERMISSION_GRANT_RESTRICTED` (kept; never reachable by non-superadmins today) |
| Access levels | `FEATURE_NOT_FOUND` (404), `FEATURE_NOT_APPLICABLE` (422) |
| Users | `USER_NOT_FOUND`, `USER_INACTIVE`, `INVALID_TELEGRAM_USERNAME`, `DUPLICATE_TELEGRAM_USERNAME`, `GM_ALREADY_EXISTS`, `POSITION_REQUIRED`, `POSITION_NOT_ALLOWED` |
| Suppliers & customers | `SUPPLIER_NOT_FOUND`, `CUSTOMER_NOT_FOUND`, `DUPLICATE_PHONE` (409), `INVALID_PHONE` (422, `details.min_digits` / `max_digits`), `SUPPLIER_INACTIVE` (422, production step 1 finish) |
| Production | `PRODUCTION_NOT_FOUND` (404), `PRODUCTION_STEP_NOT_READY` (409), `PRODUCTION_STEP_FINISHED` (409), `PRODUCTION_STEP_LOCKED` (409; no longer raised, kept for compatibility), `PRODUCTION_BALANCE_MISMATCH` (422, `details.wings` / `details.thighs`), `PRODUCTION_CONFLICT` (409, `details.batch`), `PRODUCTION_CANCELLED` (409), `PRODUCTION_COMPLETED` (409) |
| Generic | `VALIDATION_ERROR` (with `details.fields`), `NOT_FOUND`, `METHOD_NOT_ALLOWED`, `HTTP_ERROR` |

Codes are defined in `app/core/errors.py`. **Never rename a code:** the UI depends on them.

---

## 10. Endpoint reference

All paths are prefixed with `/api/v1`. Interactive docs are at `/docs`.

| Method | Path | Guard |
|---|---|---|
| POST | `/auth/login` | public |
| POST | `/auth/telegram` | public |
| POST | `/auth/refresh` | refresh token |
| POST | `/auth/logout` | signed in (allowed while a password change is pending) |
| POST | `/auth/change-password` | signed in (allowed while a password change is pending) |
| GET | `/auth/me` | signed in (allowed while a password change is pending) |
| PATCH | `/me` | signed in |
| POST | `/me/reset-password` | `users.reset_password` |
| GET | `/users` | `users.view` |
| GET | `/users/positions` | `users.view` (scoped) |
| POST | `/users` | `users.create` + manageable role |
| GET | `/users/{id}` | `users.view` + scope |
| PATCH | `/users/{id}` | `users.update` + scope |
| POST | `/users/{id}/role` | `users.update` + current and new role manageable |
| POST | `/users/{id}/deactivate` | `users.delete` + scope |
| POST | `/users/{id}/reactivate` | `users.delete` + scope |
| POST | `/users/{id}/reset-password` | `users.reset_password` + scope |
| GET | `/permissions` | role: superadmin |
| GET | `/users/{id}/permissions` | role: superadmin |
| PUT | `/users/{id}/permissions/{code}` | role: superadmin + grant rules |
| DELETE | `/users/{id}/permissions/{code}` | role: superadmin + grant rules |
| GET | `/users/{id}/features` | `permissions.grant` + scope |
| PUT | `/users/{id}/features/{feature}` | `permissions.grant` + scope + level rules (§12) |
| GET | `/audit-logs` | role: superadmin or general manager |
| GET | `/suppliers` | `suppliers.view` |
| GET | `/suppliers/stats` | `suppliers.view` |
| POST | `/suppliers` | `suppliers.create` |
| GET | `/suppliers/{id}` | `suppliers.view` |
| PATCH | `/suppliers/{id}` | `suppliers.update` |
| POST | `/suppliers/{id}/deactivate` | `suppliers.delete` |
| POST | `/suppliers/{id}/reactivate` | `suppliers.delete` |
| GET, POST, PATCH | `/customers…` | same seven routes, guarded by `customers.*` |
| GET | `/production` | `production.view` |
| GET | `/production/stats` | `production.view` |
| GET | `/production/supplier-options` | `production.create` |
| POST | `/production` | `production.create` |
| GET | `/production/{id}` | `production.view` |
| PATCH | `/production/{id}/raw-material` · `/produced` · `/standardize` | `production.create` |
| POST | `/production/{id}/{step}/finish` | `production.create` |
| POST | `/production/{id}/{step}/reopen` | `production.update` |
| POST | `/production/{id}/cancel` | `production.delete` |
| GET | `/health` (no prefix) | public |
| GET | `/docs`, `/redoc`, `/openapi.json` (no prefix) | only when API docs are enabled (development by default, §13) |

---

## 11. Suppliers & customers

Two lists with the same shape and rules, kept in separate tables (`suppliers`, `customers`). Both appear under **Workstation** (កន្លែងការងារ) in the UI.

### 11.1 Fields

| Field | Rules |
|---|---|
| `name` | Required, at most 150 characters. Trimmed, with internal whitespace collapsed. Empty after trimming → `VALIDATION_ERROR`. Khmer is kept as typed. |
| `location` | Optional free text, at most 255 characters. Trimmed; empty → `null`. |
| `phone` | Optional. Normalized (below); empty → `null`. |
| `is_active`, `deleted_at` | Soft delete, as for users. |
| `created_by`, `updated_by`, `created_at`, `updated_at` | Returned as compact user references `{id, full_name}`. |

**Phone numbers** (`core/phones.py`):

- Spaces, dashes, dots and parentheses are stripped and an optional leading `+` is kept. The result must be 8–15 digits, otherwise `INVALID_PHONE`.
- The normalized value is stored, e.g. `012 345 678` → `012345678`, `+855 12-345-678` → `+85512345678`. Local and international forms are **not** converted into each other.
- Responses also carry `phone_display`, a readable form: `012 345 678`, `+855 12 345 678`.
- **One active record per phone number, per list.** A partial unique index (`uq_<table>_active_phone`, `WHERE is_active AND phone IS NOT NULL`) backs a friendly pre-check → `409 DUPLICATE_PHONE`. It applies on create, on update and on reactivation. A deactivated record's number can be reused. The same number may appear once in suppliers and once in customers.

### 11.2 Access

- Permissions alone decide access (§5.2). There is **no role-scope check**: partners are not users.
- Staff have nothing by default. The general manager sets the Suppliers / Customers feature: **View only** lets them list and open records; **Full access** also lets them add, edit and deactivate (§12).

### 11.3 List, search and figures

`GET /suppliers` (and `/customers`):

| Parameter | Values |
|---|---|
| `q` | Case-insensitive match on name or location, or on the phone's digits (`012 345` finds `012345678`; `+855 97` finds `+85597…`). |
| `status` | `active` (default), `inactive`, `all` |
| `sort` | `name` (default, case-insensitive), `-name`, `created_at`, `-created_at` |
| `page`, `page_size` | Default 20, maximum 100 |

`GET /suppliers/stats` returns `{ total_active, new_this_month, inactive }`:

- `new_this_month` counts records **added** since the start of the current calendar month in `BUSINESS_TIMEZONE` (default `Asia/Phnom_Penh`, UTC+7), whatever their status now. For example, at 2026-09-30 18:00 UTC it is already October in Phnom Penh.

### 11.4 Changes

- `PATCH` applies only the fields present in the body. `null` or `""` clears `location` / `phone`; `name` can't be cleared.
- An update that changes nothing writes no audit entry.
- Deactivating an inactive record, or reactivating an active one, is idempotent: `200` with the record, no audit entry.
- Every change sets `updated_by` / `updated_at` and writes an audit entry (§6) with `entity_type` / `entity_id`.

---

## 12. Feature access levels

The general manager's way to give access. Each feature switches a group of detailed permissions at once: **Off**, **View only**, **Record** (only features that define it) or **Full access**.

### 12.1 Registry

`FEATURES` in `app/permissions/registry.py`. Each feature has `code`, `menu` (`workstation` | `settings`, listed in that order in `MENUS`; startup validation rejects any other value), names and descriptions in Khmer and English, `applies_to` (roles it can be set for) and `levels`: an ordered mapping level → the exact permission codes of that level, always starting with `off` → none.

| Feature | Menu | Applies to | View only | Record | Full access |
|---|---|---|---|---|---|
| `suppliers` | workstation | GM, supervisor, staff | `suppliers.view` | — | `suppliers.view/create/update/delete` |
| `customers` | workstation | GM, supervisor, staff | `customers.view` | — | `customers.view/create/update/delete` |
| `production` | workstation | GM, supervisor, staff | `production.view` | `production.view/create` | `production.view/create/update` |
| `staff_management` | settings | GM, supervisor | `users.view` | — | `users.view/create/update` |

**Record** means "can start batches and fill in steps, but can't reopen finished steps". **Full access** in Production adds reopening finished steps; cancelling batches (`production.delete`) is GM-only and outside the levels.

**Feature levels for the general manager.** Every feature also applies to the GM, but only the superadmin manages the GM (role scope), so only the superadmin sets them, on the GM's Access tab. The GM never sees or changes its own levels (`FORBIDDEN_SCOPE` on `/users/{own id}/features`). A GM with default permissions reads as **Full access** everywhere. The GM-only powers (`users.delete`, `users.reset_password`, `permissions.grant`, `production.delete`) are not in any feature and stay detailed permissions, set by the superadmin on **Permissions (advanced)**; level changes never touch them. Note that Staff management below *Full access* takes creating / editing users (or, at *Off*, the Users list) away from the GM, and revoking `permissions.grant` removes the GM's Access tab for everyone it manages.

- `users.delete`, `users.reset_password` and `permissions.grant` belong to **no** feature: they stay general-manager-only and are managed as detailed permissions by the superadmin.
- **Startup validation** (`validate_features`, at import and in bootstrap): every code a feature uses exists, is assignable to every role in `applies_to`, and has no `grantable_by`; the first level is `off` with no codes; levels are unique and follow the order `off` → `view` → `record` → `full` (`LEVELS`), where any after `off` may be omitted (only production uses `record`). A mismatch stops the API from starting.

### 12.2 Current level

A user's level for a feature is the level whose code set **exactly equals** the user's effective permissions restricted to that feature's codes. No exact match (e.g. only `suppliers.view` + `suppliers.update`, set by the superadmin) → `custom`.

### 12.3 Endpoints

**The general manager can set any level of any feature** that applies to a supervisor or staff member (the superadmin also to the GM). Unlike detailed grants, the GM's own feature permissions don't matter here: the Access layer is theirs. (Detailed permissions, §5.4, stay superadmin-only.)

`GET /users/{id}/features` (`permissions.grant` + scope) returns the features that apply to the target's role, grouped by menu (workstation first, then settings; empty menus omitted). Each feature: `code`, `menu`, names/descriptions, `levels` (in order: 4 for production, 3 for the others), `current_level` (`off` / `view` / `record` / `full` / `custom`) and `can_edit` (the actor manages access and the target, and the target is active).

`PUT /users/{id}/features/{feature}` with `{ "level": "off" | "view" | "record" | "full" }` (one of the feature's levels) checks, in order:

1. `permissions.grant` (route guard) → `MISSING_PERMISSION`
2. the target exists and is visible to the actor (§13) → `USER_NOT_FOUND`; the target is in scope → `FORBIDDEN_SCOPE`
3. the feature exists → `FEATURE_NOT_FOUND`
4. it applies to the target's role → `FEATURE_NOT_APPLICABLE`
5. the level exists for the feature → `VALIDATION_ERROR`
6. the target is active → `USER_INACTIVE`

It then applies a **diff within the feature's codes only** (grants the missing codes with `granted_by` = actor, revokes the extra ones) in one transaction; the user's other permissions are untouched. Setting `custom` → a level overwrites it. Setting the current level again is a no-op: `200`, nothing written. Each change writes one `feature.set` audit entry (§6).

The superadmin can use these endpoints too.

---

## 13. Visibility and redaction

**The superadmin is invisible to everyone else.** Nothing the general manager, supervisors or staff can reach reveals the superadmin's id, login name, full name or role.

- **User references** in every response use one schema (`schemas.common.UserRef`: `id`, `full_name`, `role`, `telegram_username`, `is_system`). For a viewer who isn't the superadmin, a reference to the superadmin serializes as `{ "id": null, "full_name": "System", "role": null, "telegram_username": null, "is_system": true }`. This covers `created_by` on users (including the GM's own record in `/auth/me`) and on suppliers/customers, `updated_by`, and the audit log's `actor` / `target`. It is applied at serialization time (`services/redaction.py`), so new endpoints are covered as long as they use `UserRef`. Without a known viewer it fails closed (hidden).
- **GM feature levels** are visible only to the superadmin: only it manages the GM, and `feature.set` entries it makes are left out of the GM's audit log like everything else it does.
- **Lookups by id:** every per-user endpoint (`GET/PATCH /users/{id}`, deactivate, reactivate, reset-password, features, …) answers `404 USER_NOT_FOUND` when a non-superadmin asks for the superadmin, not `403 FORBIDDEN_SCOPE`, which would confirm it exists.
- **Audit log for the general manager:** left out are every entry **made by** the superadmin, every entry whose **target** is the superadmin (e.g. its sign-ins), and all `permission.grant` / `permission.revoke` entries (incl. `default_backfill`); the GM sees `feature.set` instead. Entries without an actor (failed sign-ins, lockouts) stay. The `actor_id` / `target_user_id` filters never match the superadmin.
- **Wording:** no error message, detail or schema text reachable by non-superadmins names the superadmin or lists roles. `FORBIDDEN_ROLE` carries no `allowed_roles`; `FORBIDDEN_SCOPE` doesn't name the role; `422` messages for enum/literal fields don't list the allowed values.
- **API docs** (`/docs`, `/redoc`, `/openapi.json`) describe every role, so they are served only when `API_DOCS_ENABLED=true`, or when it is unset and `ENVIRONMENT=development` (the default). Set `ENVIRONMENT=production` in production.
- **UI:** one build for everyone. The superadmin's role label is "System" / "ប្រព័ន្ធ", like the API's redacted references; its extra screens are runtime checks. Their code is in the bundle (visible in browser dev tools), but they never receive superadmin data because the API redacts it.
- **Tests:** `tests/test_redaction.py` calls every GET route (from the OpenAPI schema) plus key mutations as a GM, a supervisor and staff, over data the superadmin created, and fails if a body contains the superadmin's id, name or the word "superadmin".
- **Not covered (known):** five wrong passwords for the login name `superadmin` on the login page return "account locked", which reveals that the account exists.

---

## 14. Production

Production records one **batch** as it moves through three steps. Each step is saved as a **draft** while it's filled in (autosave) and locked by **Finish**. It appears under **Workstation → Production** (ផលិតកម្ម) in the UI.

```
New production → batch PR-YYYYMMDD-NNN
  Step 1 Intake (ការនាំចូល)         → Finish → import date (ថ្ងៃនាំចូល) recorded
  Step 2 Processing (ការផលិត)       → Finish → production date (ថ្ងៃផលិត) recorded   (only after step 1 is finished)
  Step 3 Standardize (ការវេចខ្ចប់)   → Finish → packing date (ថ្ងៃវេចខ្ចប់) recorded   (only after step 2 is finished) → batch completed
```

The API step codes stay `raw-material`, `produced` and `standardize` (URLs, `steps`, audit details); only the displayed names changed.

### 14.1 Steps and fields

Weights are exact decimals (`NUMERIC`, `Decimal` in Python), accepted as JSON numbers or strings and **always returned as fixed-precision strings**: kg with 3 decimals (`"12.500"`), grams with 1 (`"350.0"`). Counts are whole numbers. Draft saves only check types and ≥ 0; Finish checks the rules below.

**Step dates, recorded by the server at Finish.** Each step has one date, set when the step is finished to **today in `BUSINESS_TIMEZONE`** (17:30 UTC on 30 Sep is already 1 Oct in Phnom Penh) and returned inside that step's object:

| Date | Step object field | Column |
|---|---|---|
| Import date (ថ្ងៃនាំចូល) | `raw_material.import_date` | `production_raw_materials.import_date` |
| Production date (ថ្ងៃផលិត) | `produced.production_date` | `production_outputs.production_date` |
| Packing date (ថ្ងៃវេចខ្ចប់) | `standardize.packaging_date` | `production_packaging.packaging_date` |

- A draft step's date is `null`.
- Dates are **never accepted from clients**: sending one in a create, draft or finish body is a `VALIDATION_ERROR` (like the computed counts), so nobody can type or backdate one.
- Steps finish in order and reopening sends every later step back to draft (clearing its date, §14.2), so **import ≤ production ≤ packing** always holds and no date is in the future. No separate check or error code is needed; a test runs reopen / re-finish sequences to prove it.
- There is no batch-level date any more; batch responses have `created_at` plus the three step dates.

**Step 1: Intake** (one line per batch)

| Field | Draft | Finish |
|---|---|---|
| `supplier_id` | optional (must exist) | required; the supplier must be **active** at finish time → else `SUPPLIER_INACTIVE` |
| `material_kind` | `chicken` (the only kind today, from the catalog) | required, known kind |
| `weight_kg` | optional, ≥ 0, max 3 decimals | required, > 0 |
| `quantity` (chickens) | optional, whole ≥ 0 | required, > 0 |

**Step 2: Processing**

| Field | Unit | Rule |
|---|---|---|
| `wings_kg`, `thighs_kg` | kg | Finish: required, > 0 |
| `wings_count`, `thighs_count` | pieces | **Computed by the server** = quantity × pieces per chicken (2 each for `chicken`). Never accepted from the client (sending them is a `VALIDATION_ERROR`). Recomputed whenever the step 1 quantity changes (e.g. after reopening step 1) and at Finish. |
| By-products: gizzard (កោះមាន់), liver (ថ្លើមមាន់), heart (បេះដូងមាន់), head (ក្បាលមាន់) | kg | Finish: required, ≥ 0 (0 allowed) |
| `marinade_g` (ទឹកប្រឡាក់) | g | Finish: required, ≥ 0 |

**Step 3: Standardize**

| Field | Rule |
|---|---|
| `big_packages` | whole ≥ 0; 1 big = 2 wings + 2 thighs |
| `small_packages` | whole ≥ 0; 1 small = 1 wing + 1 thigh |
| `rejected_wings`, `rejected_thighs` | whole ≥ 0 |
| Per by-product: `carry_kg` (carried forward), `rejected_kg` | Finish: required, ≥ 0 |
| `comment` | optional, at most 1000 characters (trimmed; empty → null) |

All of these are required at Finish.

**Piece balance: enforced by the API at Finish** (`422 PRODUCTION_BALANCE_MISMATCH`):

```
2 × big + small + rejected_wings  = wings_count
2 × big + small + rejected_thighs = thighs_count
```

`details` has `{ wings: {expected, assigned, difference}, thighs: {…} }` (`difference` = expected − assigned).

**By-product balance: UI only, NOT enforced by the API.** For each by-product the UI requires `carry_kg + rejected_kg = produced kg` exactly before Finish is enabled. The API only checks that both values are present and ≥ 0, and accepts a batch whose by-products don't add up. This is deliberate (the rule may be relaxed later) and covered by a test.

**Catalogs** (`app/production/catalog.py`): the by-products (`code`, `name_en`, `name_km`, unit `kg`, display order) and material kinds (`chicken`: 2 wings and 2 thighs per chicken). Every batch response includes them (`catalog`) so the UI renders them. Adding a by-product or kind is a catalog entry, no migration.

### 14.2 Lifecycle

- Batch `status`: `in_progress` → `completed` (step 3 finished), or `cancelled`. `current_step` (1–3) is the step being worked on.
- Step `status`: `draft` → `finished`. A step's row exists once the previous one has been finished (`produced` / `standardize` are `null` in responses until then). A finished step is read-only: saving or finishing it again → `PRODUCTION_STEP_FINISHED`. Saving or finishing a step whose previous one isn't finished → `PRODUCTION_STEP_NOT_READY`.
- **Reopen** step N (`production.update`): allowed for any finished step of an in-progress or completed batch, whatever the later steps are. In one transaction (batch row locked), step N **and every later finished step** go back to `draft` (`finished_by` / `finished_at` and **the step's date** cleared; the next Finish records that new day); **all values are kept**; `current_step` becomes N; a completed batch goes back to `in_progress` (`completed_at = null`); `version` + 1. The later steps are then finished again in order (`PRODUCTION_STEP_NOT_READY` otherwise), which recomputes the step 2 counts from step 1 and re-checks the piece balance at step 3. Each step in a batch response carries `reopens_steps` (the steps editing it would put back to draft; `[]` when it isn't finished or the batch is cancelled) so the UI can warn. Reopening a step that is already a draft changes nothing. `PRODUCTION_STEP_LOCKED` is no longer raised.
- **Cancel** (`production.delete`, general manager and superadmin only): only `in_progress` batches (`PRODUCTION_COMPLETED` for completed ones), with a required reason (1–500 characters). A cancelled batch is read-only (`PRODUCTION_CANCELLED` for any change) and excluded from the figures.
- **Batch code** `PR-YYYYMMDD-NNN`: from the **creation day** in `BUSINESS_TIMEZONE` (e.g. 17:30 UTC on 30 Sep is already 1 Oct in Phnom Penh), numbered per day by a counter row (`production_batch_counters`, `INSERT … ON CONFLICT … RETURNING`), so concurrent creations get distinct numbers. The code never changes, whenever the steps are finished or reopened.

### 14.3 Drafts and versions

- `PATCH /production/{id}/raw-material` (`/produced`, `/standardize`) takes a **partial** body: only fields present are applied, `null` clears one. `produced` and `standardize` take `byproducts` as a map by item code (`{"liver": "0.4"}`, `{"liver": {"carry_kg": "0.3"}}`); unknown codes → `VALIDATION_ERROR`.
- Every write (draft save, finish, reopen, cancel) requires the batch **`version`** it's based on and increments it. A stale version → `409 PRODUCTION_CONFLICT` with the current batch in `details.batch`, so the client can show what changed and retry.
- Writes lock the batch row (`SELECT … FOR UPDATE`). Checks run in this order: not found, cancelled, step state, version, values.

### 14.4 Endpoints and figures

| Endpoint | Notes |
|---|---|
| `GET /production` | **Cancelled batches are left out** unless `include_cancelled=true` (then added to the chosen status) or `status=cancelled` (only them). Filters: `status` (`in_progress`, `completed`, `cancelled`, `all` = default: in progress + completed), `include_cancelled` (default `false`), `waiting_step` (2 or 3: in-progress batches whose previous steps are finished and that step isn't), `date_from` / `date_to` (inclusive; a batch matches if **any** of its three step dates is in the range, or, while no step is finished, its **creation day**), `q` (batch code or supplier name). `sort`: `-date` (default), `date` — by the batch's **latest recorded step date**, falling back to its creation day, then by code — `code`, `-code`. Paging: 20 by default, at most 100. Items: `code`, `import_date`, `production_date`, `packaging_date` (null until recorded), `created_at`, `status`, `current_step`, `steps` (`pending` / `draft` / `finished` for steps 1–3), `supplier`, `quantity`, `created_by`. |
| `GET /production/stats` | `in_progress`; `completed_today` (completed since midnight, Cambodia time); `chickens_this_month` (quantity of finished step 1s whose **import date** is this month); `rejected_pieces_this_month` (rejected wings + thighs of finished step 3s whose **packing date** is this month). Months and days follow `BUSINESS_TIMEZONE`; cancelled batches are excluded. |
| `POST /production` | Creates the batch with a draft step 1; optional initial step 1 fields (no date). `201` with the batch. |
| `GET /production/{id}` | The batch, all steps, by-products, catalogs and `computed` (`wings_count` / `thighs_count` from the current quantity, `yield_percent` = (wings kg + thighs kg) ÷ raw kg × 100, one decimal, or null). |
| `POST /production/{id}/{step}/finish` | `step` ∈ `raw-material`, `produced`, `standardize`; body `{version}`. Records the step's date (today, `BUSINESS_TIMEZONE`). |
| `POST /production/{id}/{step}/reopen` | Body `{version}`. Reopens a finished step: it and every later finished step go back to draft (§14.2). |
| `POST /production/{id}/cancel` | Body `{version, reason}`. |
| `GET /production/supplier-options` | Active suppliers `{id, name, phone_display}` (at most 20, `q` on name or phone digits), for picking the step 1 supplier **without** Suppliers access. |

Every user reference (`created_by`, `finished_by`, …) is a `UserRef` and redacted like everywhere else (§13); the GET routes are part of the redaction sweep.

### 14.5 Access

| Level (feature `production`) | Can |
|---|---|
| Off | nothing |
| View only | list, open batches and see figures |
| Record | also start batches, fill in steps (drafts) and finish them, pick suppliers |
| Full access | also reopen finished steps (one action; later steps go back to draft) |
| (GM only, detailed permission) | cancel batches |

Defaults: the general manager holds all four permissions (and reads as Full access; the superadmin can lower it), supervisors Full access, staff Off (§5.3). Anyone with `production.create` can fill in any in-progress batch, not only their own.
