# API Features — Phase 1

What the Mean Chey Grilled Chicken API (មាន់អាំងមានជ័យ) does today. Phase 1 contains **only** authentication, user management and permission control. Business features (orders, stock, delivery, …) come in later phases and plug into the permission system described here.

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
| Deactivate / reactivate | `users.delete` | yes | Soft delete: `is_active=false`, `deleted_at`. Reactivation re-checks the single-GM and username uniqueness rules. |
| Reset password | `users.reset_password` | yes | §2 |
| Edit own profile | signed in | self | `PATCH /me`: name, phone, language |

---

## 5. Permission system

### 5.1 Registry (code is the source of truth)

Permissions are declared in `app/permissions/registry.py`. Each entry has:

- `code`, `module`
- `name_en`, `name_km`
- `description_en`, `description_km`
- `assignable_to`: the roles that may ever hold it.

On every startup the registry is **synced** into the `permissions` table:

- new entries are inserted;
- names, descriptions and `assignable_to` are updated;
- entries removed from the registry are marked `is_active = false` and never deleted, so the grant history stays intact.

Inactive permissions are ignored everywhere: effective permissions, catalog, grants.

### 5.2 Phase 1 permissions (module `users`)

| Code | Meaning | Assignable to |
|---|---|---|
| `users.view` | View users in own scope | GM, supervisor |
| `users.create` | Create users in own scope | GM, supervisor |
| `users.update` | Edit users in own scope | GM, supervisor |
| `users.delete` | Deactivate / reactivate users in own scope | GM, supervisor |
| `users.reset_password` | Reset passwords (others in scope, and self) | GM only |
| `permissions.grant` | Grant / revoke permissions in own scope | GM, supervisor |

No Phase 1 permission is assignable to staff.

### 5.3 Defaults

| Role | On creation |
|---|---|
| Superadmin | Implicitly holds **every** active permission. Nothing is stored. |
| General manager | All six Phase 1 permissions. |
| Supervisor | `users.view`, `users.create`, `users.update`, limited to what the creator holds. |
| Staff | None. |

### 5.4 Grant rules

`PUT /users/{id}/permissions/{code}` grants a permission; `DELETE /users/{id}/permissions/{code}` revokes it. Checks, in order:

1. The actor holds `permissions.grant`. Otherwise → `MISSING_PERMISSION`.
2. The target is in the actor's scope. Otherwise → `FORBIDDEN_SCOPE`.
3. The permission exists and is active. Otherwise → `PERMISSION_NOT_FOUND`.
4. The actor holds that permission themselves, for grant **and** revoke. Otherwise → `PERMISSION_NOT_HELD`.
5. For grants, two more checks:
   - the target is active. Otherwise → `USER_INACTIVE`.
   - the target's role is in `assignable_to`. Otherwise → `PERMISSION_NOT_ASSIGNABLE`.

Grant and revoke are idempotent.

**Revoking doesn't cascade.** When permission *P* is revoked from user *U*, any grants of *P* that *U* made to others stay in place. The `permission.revoke` audit entry lists them in `details.downstream_grants`, and the UI highlights them for follow-up.

### 5.5 Effective permissions

`GET /auth/me` returns `permissions`: the user's effective codes, meaning active permissions that are granted to them and still assignable to their role. It also returns `manageable_roles` and `can_self_reset_password`, so the UI can build menus and forms.

`GET /users/{id}/permissions` returns every permission assignable to the target's role, grouped by module. Each item has:

- `granted`, `granted_by`, `granted_at`;
- `can_edit`: true when the actor could change this permission on this user, per the rules in §5.4.

---

## 6. Audit log

Every security-relevant action writes to `audit_logs` (`actor_id`, `action`, `target_user_id`, `details` JSONB, `created_at`):

| Area | Actions |
|---|---|
| Authentication | `auth.login` (method: password / telegram), `auth.login_failed` (with reason), `auth.locked`, `auth.logout`, `auth.password_changed`, `auth.telegram_bound` |
| Users | `user.create` (includes default permissions), `user.update` (field diff), `user.deactivate`, `user.reactivate`, `user.password_reset`, `user.password_self_reset` |
| Permissions | `permission.grant`, `permission.revoke` (includes `downstream_grants`) |
| Profile | `profile.update` |

`GET /audit-logs` is available to the **superadmin and general manager only**. This is a role check, not a permission. It supports filters (`action`, `actor_id`, `target_user_id`, `date_from`, `date_to`) and paging. Each entry includes compact actor and target references.

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
| Authorization | `FORBIDDEN_SCOPE`, `FORBIDDEN_ROLE`, `MISSING_PERMISSION`, `PERMISSION_NOT_HELD`, `PERMISSION_NOT_ASSIGNABLE`, `PERMISSION_NOT_FOUND` |
| Users | `USER_NOT_FOUND`, `USER_INACTIVE`, `INVALID_TELEGRAM_USERNAME`, `DUPLICATE_TELEGRAM_USERNAME`, `GM_ALREADY_EXISTS`, `POSITION_REQUIRED`, `POSITION_NOT_ALLOWED` |
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
| POST | `/users/{id}/deactivate` | `users.delete` + scope |
| POST | `/users/{id}/reactivate` | `users.delete` + scope |
| POST | `/users/{id}/reset-password` | `users.reset_password` + scope |
| GET | `/permissions` | signed in |
| GET | `/users/{id}/permissions` | `users.view` + scope |
| PUT | `/users/{id}/permissions/{code}` | `permissions.grant` + grant rules |
| DELETE | `/users/{id}/permissions/{code}` | `permissions.grant` + grant rules |
| GET | `/audit-logs` | role: superadmin or general manager |
| GET | `/health` (no prefix) | public |
