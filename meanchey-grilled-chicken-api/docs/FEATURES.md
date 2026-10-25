# API Features — Phase 1

What the Mean Chey Grilled Chicken API (មាន់អាំងមានជ័យ) does today. Phase 1 covers authentication, user management and access control (feature access levels over detailed permissions, §5 and §12). The business features, **suppliers and customers** (§11), **production** (§14), **inventory** (§18), **orders** (§19) with their **delivery notes** (§19.6), the **business info** printed on them (§20) **preparation** (§21: satay sachets and packaging materials made ready from raw materials) and **attendance** (§22: GPS check-in / check-out from the Mini App, shifts, reminders, absences, corrections), plug into the permission system described here, as will later ones.

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
- [15. Packaging plan](#15-packaging-plan)
- [16. Notifications](#16-notifications)
- [17. Role limits](#17-role-limits)
- [18. Inventory](#18-inventory)
- [19. Orders](#19-orders)
- [20. Business info](#20-business-info)
- [21. Preparation](#21-preparation)
- [22. Attendance](#22-attendance)

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
   - The same binding also happens when the user presses **Start** in the bot (§7.4), so alerts and attendance reminders reach users who never opened the Mini App.
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

**Password reset** — allowed for the superadmin and general managers only:

| Action | Endpoint | Result |
|---|---|---|
| Reset a user in scope | `POST /users/{id}/reset-password` | Password becomes their Telegram username, `must_change_password = true`, all sessions revoked, lock cleared. |
| GM resets self | `POST /me/reset-password` | Password becomes their Telegram username, must change at next login, all sessions revoked. |
| Superadmin resets self | `POST /me/reset-password` | Password becomes `SUPERADMIN_INITIAL_PASSWORD`, **no** forced change, all sessions revoked. |

This is enforced through the `users.reset_password` permission, whose `assignable_to` is `[general_manager]`. Supervisors can never receive it.

---

## 3. Roles and hierarchy

| Role | How many active | Created by | Manages |
|---|---|---|---|
| `superadmin` | exactly 1, seeded | bootstrap | general managers, supervisors, staff |
| `general_manager` | up to the **role limit** (default **2**) | superadmin | supervisors, staff |
| `supervisor` | up to the role limit (default **3**, may be unlimited) | a general manager (or superadmin) | staff |
| `staff` | up to the role limit (default **10**, may be unlimited) | a GM, a supervisor (or superadmin) | nobody |

The limits are set by the superadmin (§17).

- **Role decides WHO** a user may act on. **Permissions decide WHAT** they may do.
- Nobody can act on a user at the same or a higher level, including themselves. Users edit themselves through `/me`. With several general managers, **a GM can't view, edit, deactivate, reset, change the role of or set access for another GM** (`403 FORBIDDEN_SCOPE`); only the superadmin manages GMs. Everything else is shared: every GM manages all supervisors and staff, sees the same audit log (when the superadmin allows it, §6) and receives the production alerts.
- Roles can be changed (promote / demote, §4); the new role needs a free slot under its limit (§17).
- **Attendance** (§22) is recorded for active **staff and supervisors** only; each has a workplace (`users.workplace_id`, the default one), never the general manager or the superadmin.

**Invariants enforced by the database**

| Rule | Mechanism |
|---|---|
| Only one superadmin | Partial unique index `uq_users_single_superadmin` |
| At most N active users per role (general manager, supervisor, staff) | `role_limits` row locked while counting (§17); the single-GM index `uq_users_single_active_gm` was dropped in migration `0008` |
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
| Create a user | `users.create` | Role must be manageable | Default permissions are granted automatically (§5.3). The role needs a free slot (`409 ROLE_LIMIT_REACHED`, §17). Supervisors: only when a GM set their Staff management to **Record** or **Full access** (default View only). |
| Edit a user | `users.update` | yes | Name, phone, language, position (staff, free text), Telegram username. Changing the username unbinds the Telegram account. Supervisors: only at Staff management **Full access**. |
| Change role (promote / demote) | `users.update` | current **and** new role manageable | `POST /users/{id}/role` `{role, position?}`. The actor must manage both the current and the new role: the **general manager** moves users between **staff and supervisor**; the **superadmin** between **general manager, supervisor and staff**. Supervisors can't change roles, and nobody changes their own. The new role's default access **replaces** the old one (supervisor: the supervisor defaults of §5.3; staff: every feature Off; general manager: all GM permissions); adjust it afterwards with feature levels. Demoting to staff needs a `position`; promoting clears it (`POSITION_REQUIRED` / `POSITION_NOT_ALLOWED`). The new role needs a free slot when the user is active (`ROLE_LIMIT_REACHED`, §17); an inactive user changes role freely (reactivating checks later). Same role again: no-op, no check. The username, password and Telegram link are kept. |
| Deactivate / reactivate | `users.delete` | yes | Soft delete: `is_active=false`, `deleted_at`. Reactivation re-checks the role limit (`ROLE_LIMIT_REACHED`) and username uniqueness. Deactivating frees a slot. |
| Reset password | `users.reset_password` | yes | §2 |
| Edit own profile | signed in | self | `PATCH /me`: name, phone, language |
| Set staff access (feature levels) | `permissions.grant` or `users.manage_access` | yes | §12.3. A supervisor (`users.manage_access`) reaches staff only and can't give more than it has. |

**Workplace (attendance, §22.1):** staff and supervisors are assigned to one workplace. Create, edit and role change take `workplace_id` (an active workplace; others → `404 ATTENDANCE_WORKPLACE_NOT_FOUND` / `409 WORKPLACE_ARCHIVED`; other roles → `422`); without it they keep an active one or get the **default workplace**. Reactivation keeps it while active, else the default; a change to general manager keeps the (unused) link. Changes are in `user.update` (`changes.workplace`) and `user.role_change` (`workplace`). `UserOut.workplace` is `{id, name}` or null; `GET /users?workplace_id=` filters by it.

**Attendance start date and tracking (attendance, §22.1):**

- `attendance_start_date` (date): the first day attendance is tracked. **Required for staff and supervisors** (set by the API), null for general managers and the superadmin (giving one → `422 VALIDATION_ERROR`). `UserOut` also carries `attendance_tracked` and `attendance_untracked_since`.
- **Create:** `attendance_start_date` defaults to **today** (`BUSINESS_TIMEZONE`); a past date → `422 VALIDATION_ERROR` with `details.code = ATTENDANCE_START_IN_PAST`.
- **Edit** (`PATCH /users/{id}`): editable only while the current date is still in the future (the new value again today or later); once it has arrived → `409 ATTENDANCE_START_LOCKED` (`details.start_date`). The same value is a no-op.
- **Role change** into staff / supervisor from another kind of role takes `attendance_start_date` (default today, same rules); staff ↔ supervisor keeps the date (a given one follows the edit rules); a change to general manager clears it. Audit: `user.create` (`attendance_start_date`), `user.update` (`changes.attendance_start_date`), `user.role_change` (`attendance_start_date_from` / `_to`).
- **Track attendance** (`attendance_tracked`, default true): staff are always tracked; only a **supervisor** can be switched off, with `PATCH /users/{id}` `{attendance_tracked: false|true}` (`users.update` + scope: the superadmin and general managers; a supervisor manages no supervisor and nobody edits themselves here). For staff `true` is a no-op and `false` → `422 VALIDATION_ERROR`; for the other roles any value → `422`. Off opens a period **from today**, on closes it at yesterday (or removes it if it began today). Role change supervisor → staff (or → GM) forces it on and closes any open period; staff → supervisor keeps it on. Audit `user.update` `changes.attendance_tracked: [from, to]`.
- Details: §22.1 (who is tracked on a date), §22.3 `me/today`, §22.6 scheduler, §22.9 summaries.

**Supervisors and staff, by default:** they **see** staff (`users.view`) and **set their access** (`users.manage_access`, Staff access), but don't add staff or edit their info. A GM (or the superadmin) allows adding (Staff management *Record*) or adding and editing (*Full access*) per supervisor. Without `users.create` / `users.update` → `403 MISSING_PERMISSION`. Supervisors never change roles or deactivate.

---

## 5. Permission system

Access has two layers:

- **Detailed permissions** (this section) are the underlying mechanism. Only the **superadmin** sees and edits them.
- **Feature access levels** (§12) sit on top. General managers set *Off / View only / [Record /] Full access* per feature for supervisors and staff, and supervisors with Staff access for staff (up to their own access); neither ever sees a permission code.

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
| `users.view` | View users in own scope | GM, supervisor | Staff management (View only and up) |
| `users.create` | Create users in own scope | GM, supervisor | Staff management (Record and up) |
| `users.update` | Edit users in own scope | GM, supervisor | Staff management (Full access) |
| `users.delete` | Deactivate / reactivate users in own scope | **GM only** | — |
| `users.reset_password` | Reset passwords (others in scope, and self) | GM only | — |
| `permissions.grant` | Set feature access levels (GM); grant / revoke detailed permissions (superadmin only, §5.4) | **GM only** | — |
| `users.manage_access` | Set feature access levels of **staff** in own scope, never above the actor's own access (§12.3) | **supervisor only** | Staff access (Full access) |

- **Supervisors never deactivate users and never hold `permissions.grant`.** `users.delete` and `permissions.grant` are no longer assignable to supervisors. Rows stored before this change stay in the table but have no effect: effective permissions filter on `assignable_to` at read time (§5.5). Supervisors set staff access with their own permission, `users.manage_access`, instead: making `permissions.grant` assignable again would silently revive those stale rows.
- `users.manage_access` is not assignable to the GM: the GM sets access with `permissions.grant`. When a GM (or the superadmin) creates a supervisor, holding `permissions.grant` counts as holding `users.manage_access` for the "limited to what the creator holds" rule (§5.3).
- No `users` permission is assignable to staff.

**Module `partners`** (§11)

| Code | Meaning | Assignable to | In feature |
|---|---|---|---|
| `suppliers.view` | View suppliers and their figures | GM, supervisor, staff | Suppliers |
| `suppliers.create` / `.update` / `.delete` | Add / edit / deactivate suppliers | GM, supervisor, staff | Suppliers |
| `customers.view` | View customers and their figures | GM, supervisor, staff | Customers |
| `customers.create` / `.update` / `.delete` | Add / edit / deactivate customers | GM, supervisor, staff | Customers |

General managers can give any of these to supervisors **and staff** through feature levels.

**Module `production`** (§14)

| Code | Meaning | Assignable to | In feature (level) |
|---|---|---|---|
| `production.view` | See batches, their steps and figures | GM, supervisor, staff | Production (View only and up) |
| `production.create` | Start batches; save drafts and finish steps | GM, supervisor, staff | Production (Record and up) |
| `production.update` | Reopen a finished step (and every later finished step with it) | GM, supervisor, staff | Production (Full access) |
| `production.delete` | Cancel a batch | **GM only** | — (detailed permission) |

**Module `production_plan`** (§15)

| Code | Meaning | Assignable to | In feature (level) |
|---|---|---|---|
| `production_plan.view` | See the Production plan tab and every plan; **receive the production alerts** (§16) | GM, supervisor | Production plan (View only and up) |
| `production_plan.manage` | Fill in, edit and confirm plans | GM, supervisor | Production plan (Full access) |

Staff can't hold either. The alerts go to whoever holds `production_plan.view`, so the plan feature is also "who gets told".

**Module `inventory`** (§18)

| Code | Meaning | Assignable to | In feature (level) |
|---|---|---|---|
| `inventory.view` | See stock, wasted items, materials and, per item, which batches its current stock came from | GM, supervisor, staff | Inventory (View only and up) |
| `inventory.history` | See every stock movement: the History tab, an item's recent changes, a batch's stock changes | GM, supervisor | Inventory history (View only; **grantor must hold it**, §12.3) |
| `inventory.materials_stock` | Add stock of materials, and take it out with a reason (§18.11) | GM, supervisor, staff | Inventory (Record) |
| `inventory.materials_manage` | Create, edit (names, unit), archive and restore materials (§18.11) | GM, supervisor | Inventory materials (Full access) |

**Module `orders`** (§19)

| Code | Meaning | Assignable to | In feature (level) |
|---|---|---|---|
| `orders.view` | See orders, their boxes, delivery status and returns | GM, supervisor, staff | Orders (View only and up) |
| `orders.create` | Create orders; move them to Delivering and Delivered; record returns | GM, supervisor, staff | Orders (Record) |
| `orders.update` | Edit Created orders | GM, supervisor | Order management (Full access) |
| `orders.cancel` | Cancel a Created order (the customer cancelled) | GM, supervisor | Order management (Full access) |
| `orders.review_returns` | Put returned items back into stock or wasted; **receive the order alerts** (§16) | GM, supervisor | Order returns (Full access) |
| `orders.export_delivery_note` | Download an order's delivery note as an Excel file (built in the browser) and read the supplier block for it | GM, supervisor, staff | Export delivery note (Full access) |
| `orders.containers` | Mark a box recorded as not returned at delivery as **returned later** (§19.7) | GM, supervisor, staff | Order containers (Full access) |

**Module `preparation`** (§21)

| Code | Meaning | Assignable to | In feature (level) |
|---|---|---|---|
| `preparation.view` | See preparations and their figures | GM, supervisor, staff | Preparation (View only and up) |
| `preparation.create` | Create, fill in and finish preparations | GM, supervisor, staff | Preparation (Record) |
| `preparation.update` | Reopen finished preparations; **receive the preparation alerts** (§16) | GM, supervisor | Preparation management (Full access) |
| `preparation.cancel` | Cancel preparations | GM, supervisor | Preparation management (Full access) |

**Module `settings`** (§20)

| Code | Meaning | Assignable to | In feature (level) |
|---|---|---|---|
| `settings.business_info` | Edit the business info printed on delivery notes (names, address, phone, logo, footer note) and preview the note | **GM only** | Business info (Full access) |
| `audit.view` | Open the audit log (§6), with the general manager's filtering (§13) | **GM only** | Audit log (View only) |

The superadmin holds both implicitly; a general manager only when the superadmin turns Business info / Audit log on for it. They're in nobody's defaults and aren't backfilled (existing GMs lost the audit log when it moved behind `audit.view`, until the superadmin allows it). Printing delivery notes needs only `orders.view` (§19.6): there is no document permission.

**Module `attendance`** (§22)

| Code | Meaning | Assignable to | In feature (level) |
|---|---|---|---|
| `attendance.view` | See each day's attendance of the employees in scope | GM, supervisor | Attendance (View only) |
| `attendance.correct` | Fix records and add missing ones, with a reason | GM, supervisor | Attendance corrections (Full access) |
| `attendance.workplace_view` | See the workplaces (location, radius, default, employees; the schedule read-only) | **GM only** | Workplaces (View only) |
| `attendance.workplace_update` | Edit existing workplaces: name, address, map position (latitude / longitude) and check-in radius | **GM only** | Workplaces (Record) |
| `attendance.workplace_manage` | Create, delete / archive and restore workplaces; make one the default | **GM only** | Workplaces (Full access) |
| `attendance.scheduling` | Manage tracked weekdays, holidays, shift times and rules for one, several or all workplaces (§22.14) | GM, supervisor | Attendance scheduling (Full access; grantor must hold it) |
| `attendance.requests_review` | Approve, change or reject the monthly attendance requests of employees in scope (§22.15) | GM, supervisor | Attendance requests (Full access) |

Migration 0024 split editing out of `attendance.workplace_manage` into `attendance.workplace_update` (Workplaces gained a Record level): every holder of `workplace_manage` also got `workplace_update` (same `granted_by`), so Full stays Full; one `permission.grant` audit entry per grant, no actor, `source: default_change`. The GM default stays View only.

`attendance.shifts_manage` (each workplace's schedule) was retired by migration 0020: its holders got `attendance.scheduling` (audited as `feature.set`, `source: default_change`); the row stays inactive.

Checking in needs no permission: tracked employees (active staff and supervisors) may, nobody else.

`inventory.adjust` (set stock values) was **removed**: every inventory item comes from production and changes only through it (§18.5). The sync marked it inactive; its rows are kept, so it can come back with manual items.

Cancelling batches is a general-manager decision, like deactivating users: `production.delete` is assignable to the GM only and belongs to no feature level. Supervisors or staff granted it before this change keep the row, but it has no effect (read-time `assignable_to` filter, §5.5), and their Production level still reads as *Full access*.

### 5.3 Defaults

| Role | On creation |
|---|---|
| Superadmin | Implicitly holds **every** active permission. Nothing is stored. |
| General manager | All `users` permissions assignable to the GM (incl. `users.delete`, `users.reset_password`, `permissions.grant`; not `users.manage_access`), all partner permissions, all four `production.*` permissions, both `production_plan.*` permissions, `inventory.view` and `inventory.materials_stock` (Inventory **Record**), `inventory.materials_manage` (Inventory materials **Full**; **not** `inventory.history`: the superadmin allows it per GM) all seven `orders.*` permissions (Orders Record, Order management Full, Order returns Full, Export delivery note Full, Order containers Full) and all four `preparation.*` permissions (Preparation Record, Preparation management Full). **Not** `settings.business_info` (Business info Off) and **not** `audit.view` (Audit log Off): the superadmin allows them per GM. Attendance **View only**, Attendance corrections **Full**, Attendance requests **Full**, Workplace **View only** (`attendance.view`, `attendance.correct`, `attendance.requests_review`, `attendance.workplace_view`); Attendance scheduling **Off** (the superadmin allows it per GM). |
| Supervisor | Suppliers, Customers and Production at **Full access** (view, record, reopen finished steps; not cancel); **Production plan Off**; **Inventory Record** (material stock), Inventory materials **Off**; **Orders Record**, Order management, Order returns, Export delivery note and Order containers **Off**; **Preparation Record**, Preparation management **Off**; Attendance and Attendance corrections **Off**; **Staff management View only** (`users.view`); **Staff access Full** (`users.manage_access`). Limited to what the creator holds (`permissions.grant` covers `users.manage_access`). The GM gives plan access (and with it the alerts) to the supervisors who need it, and allows adding / editing staff per supervisor. |
| Staff | Every feature **Off** (no permissions). |

`DEFAULT_PERMISSIONS` for supervisors and staff is computed from the feature levels, so the two can't drift apart. When the production permissions were added, the one-time backfill (§5.1) gave them to existing active general managers and supervisors; staff got nothing. The `production_plan.*` permissions were backfilled to existing active general managers only (supervisors' default is Off). `users.manage_access` is backfilled to existing **active supervisors** (Staff access Full). `inventory.view` is backfilled to existing active general managers and supervisors. `inventory.history` is in nobody's defaults, so it isn't backfilled: only the superadmin sees inventory history until it grants it. The `orders.*` permissions are backfilled per the defaults: all five to existing active general managers, `orders.view` and `orders.create` to existing active supervisors, nothing to staff. `orders.containers` (added later) was backfilled by the same sync to existing active general managers only. The `preparation.*` permissions likewise: all four to existing active general managers, `preparation.view` and `preparation.create` to existing active supervisors, nothing to staff. The `attendance.*` permissions: `attendance.view`, `attendance.correct`, `attendance.requests_review` and `attendance.workplace_view` to existing active general managers; nothing to supervisors and staff. `attendance.scheduling` is in nobody's defaults (not backfilled); migration 0020 gave it to those who held `attendance.shifts_manage`.

**Default change for existing supervisors (migration `0009`).** Staff management used to default to Full access. Migration `0009_supervisor_staff_defaults` moved every supervisor whose staff management was **exactly Full** (`users.view/create/update`) to **View only** (removes `users.create` and `users.update`), deactivated supervisors included so that reactivating doesn't bring Full back. Supervisors at a custom or lower level were left alone. Each changed supervisor got one `feature.set` audit entry with no actor (System) and `details.source = "default_change"`. It runs once (Alembic); its downgrade does nothing.

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
- `can_manage_features`: holds `permissions.grant` **or** `users.manage_access`, i.e. may set feature levels (the Access tab): the GM and the superadmin for anyone they manage, a supervisor with Staff access for staff;
- `telegram_alerts`: holds an alert permission (`production_plan.view`, `orders.review_returns`, `preparation.update`, `attendance.requests_review`, §16.1) **or** is tracked for attendance (today or starting later, §22). Alerts and reminders then go to Telegram, so with `user.telegram_linked = false` the app asks the user to open the bot and press Start.

`GET /users/{id}/permissions` (superadmin only) returns every permission assignable to the target's role, grouped by module. Each item has `granted`, `granted_by`, `granted_at`, `can_edit` and `reason` (the error code of the first rule that blocks editing, or `null`).

---

## 6. Audit log

Every security-relevant action writes to `audit_logs` (`actor_id`, `action`, `target_user_id`, `entity_type`, `entity_id`, `details` JSONB, `created_at`). `entity_type` / `entity_id` reference a non-user record (`supplier`, `customer`, `production_batch`, `order`, `material`, `preparation`); they're null for user and auth actions.

| Area | Actions |
|---|---|
| Authentication | `auth.login` (method: password / telegram), `auth.login_failed` (with reason), `auth.locked`, `auth.logout`, `auth.password_changed`, `auth.telegram_bound` |
| Users | `user.create` (includes default permissions), `user.update` (field diff), `user.role_change` (`from`, `to`, `position_from`, `position_to`, `permissions_added`, `permissions_removed`), `user.deactivate`, `user.reactivate`, `user.password_reset`, `user.password_self_reset` |
| Permissions | `permission.grant` (`details.source = "default_backfill"` and no actor when granted by the startup backfill), `permission.revoke` (includes `downstream_grants`). **Superadmin only.** |
| Access | `feature.set`: one entry per change, `details = {feature, from, to, added, removed}` (`from` may be `custom`). The actor is whoever set it (a GM, the superadmin or a supervisor). No individual `permission.*` entries are written for it. `details.source = "default_change"` and no actor: written by a migration that changed a default for existing users (migration `0009`: supervisors' Staff management Full → View only). |
| Suppliers | `supplier.create`, `supplier.update` (field diff), `supplier.deactivate`, `supplier.reactivate`. `details.name` holds the record's name. |
| Customers | `customer.create`, `customer.update` (field diff), `customer.deactivate`, `customer.reactivate`. `details.name` holds the record's name. |
| Production | `production.create`, `production.step_finish` (`step`: 1–3; step 3 also `sachets_4_used`, `sachets_2_used`), `production.step_reopen` (`step`, `reopened_steps`: e.g. `[1, 2, 3]`), `production.cancel` (`reason`). `details.code` holds the batch code. **Draft saves are not audited.** |
| Packaging plan | `production_plan.update` (`changes`: field → `[old, new]`, only when something changed), `production_plan.confirm` (`expected_big`, `expected_small`). `entity_type = production_batch`, `details.code` = the batch code. |
| Inventory | `inventory.adjust` (`item_code`, `name_en`, `name_km`, `from` / `to` = `{count, kg}`, `reason`): only entries from before production items became read-only (§18.5), kept as the record. Production movements are in the inventory history (§18), not the audit log. |
| Orders | `order.document_printed` (`copy`: the print number, 1, 2, …; `via`: `download` / `telegram`): one per delivery note generated (§19.6); the Business info preview isn't audited. `order.create` (`customer` (the name; null for a direct order), `customer_type`, `customer_phone` (readable), `customer_location`, `delivery_date`, `white_boxes`, `black_boxes`, `plastic_bag_boxes`, `delivery_bag_boxes`, `items`), `order.update` (`changes`: field → `{from, to}` for `customer`, `customer_type`, `customer_phone`, `customer_location` (the order's customer snapshot, §19.2), `delivery_date`, `driver`, `note`, `boxes` = `{white, black, plastic_bag, delivery_bag, items}`; only when something changed), `order.cancel` (`reason`), `order.delivering` (`items`: the totals that left stock), `order.delivered` (`outcome`: `accepted` / `returned`, with `reason` and `returned` items), `order.returns_reviewed` (`outcome`: `partly_returned` / `fully_returned`, `to_stock`, `to_wasted`), `order.containers_recorded` (at Delivered, when the order has returnable boxes: `boxes` = `[{box (position), color, returned, reason}]`), `order.container_returned` (a box marked returned later: `box`, `color`, the original `reason`). `order.create` also has `returnable_boxes` and `order.update`'s `boxes` diff `returnable` (the positions of the boxes to bring back). Items are `[{item_code, name_en, name_km, count, kg}]`. `entity_type = order`, `details.code` = the order code. |
| Materials | `material.create` (`unit`), `material.update` (`changes`: field → `[old, new]`, incl. `unit` and the converted `balance`), `material.archive` (`balance`), `material.restore`, `material.stock_add` / `material.stock_remove` (`quantity`, `unit`, `balance_after`; `reason` on removals). `entity_type = material`, `details.name_en` / `name_km` / `item_code`. Production's marinade movements are in the inventory history, not the audit log. |
| Preparations | `preparation.create`, `preparation.finish` (`sachets_2`, `sachets_4` (satay) or `materials`: `[{name_en, name_km, quantity, unit}]` (packaging)), `preparation.reopen`, `preparation.cancel` (`reason`, `was`: `draft` / `finished`). `entity_type = preparation`, `details.code` and `details.type`. **Draft saves are not audited**; the stock movements are in the inventory history. |
| Attendance | `attendance.attempt_refused` (a refused check-in / check-out: `action`, `code`, `shift`, `distance_m`, `accuracy_m`; actor and target = the employee), `attendance.correct` (`work_date`, `shift`, `reason`, `created`, `before` / `after` = `{status, late_minutes, check_in_at, checkout_status, check_out_at}`; `entity_type = attendance_record`, target = the employee), `workplace.create` (`name`, `address`, `latitude`, `longitude`, `radius_m`, `schedule_from`), `workplace.update` (`name`, `changes`, incl. `previous_default`), `workplace.archive` / `workplace.delete` / `workplace.restore` (`name`), all with `entity_type = attendance_workplace`. Scheduling (§22.14), one entry per write: `attendance.weekdays_update` / `attendance.schedule_update` (`workplaces` (names), `all_workplaces`, `effective_from`, `changes`: workplace name → field → `[old, new]` (shifts as `{morning: "07:00–12:00", …}`; `later_versions`: how many upcoming versions got the change too), `records_removed`, `absents_recreated`), `attendance.schedule_version_delete` (`workplace`, `effective_from`, the version's weekdays, shifts and rules), `attendance.holiday_create` / `attendance.holiday_update` (`before` / `after`) / `attendance.holiday_delete` (names, dates, `scope`, `workplaces`, `note`, effects; `entity_type = attendance_holiday`), `attendance.holiday_copy` (`from_year`, `to_year`, `created`, `skipped`), and `attendance.records_removed_by_day_off` (`cause` (the action), `effective_from` or `holiday_id` / `holiday`, `count`, `records`: each removed record's full snapshot, so it can be recovered). Requests (§22.15): `attendance.request_submit` (`year`, `month`, the snapshot figures, the requested split, `type`; actor = target = the employee), `attendance.request_approve` (`with_changes`, `before` / `after` = `{salary_cut_minutes, unpaid_work_minutes}`, `comment`), `attendance.request_reject` (`reason`), all with `entity_type = attendance_request` and the employee as target, and `attendance.settings_update` (`request_deadline_day: [from, to]`, superadmin; only when the value changed). Successful check-ins and scheduler records aren't audited: they are the records. |
| Settings | `settings.role_limit_update` (`role`, `from`, `to`; `null` = unlimited). Superadmin only, so hidden from general managers. `settings.business_update` (`changes`: field → `[old, new]` for the text fields; the logo as `"logo": "changed"` / `"removed"`, never its bytes), only when something changed (§20). A GM given Business info sees its own entries; the superadmin's are hidden from it like everything it does. |
| Profile | `profile.update`; `profile.telegram_link` / `profile.telegram_unlink` (the superadmin's Telegram link, §7.5; hidden from the GM like everything the superadmin does) |

`GET /audit-logs` needs `audit.view`: the **superadmin** always (implicit), a **general manager** only when the superadmin sets its **Audit log** feature to View only (§12.1; default Off). Supervisors and staff can't hold it. Without it → `403 MISSING_PERMISSION`. What a general manager sees is filtered as before (§13). It supports filters (`action`, `actor_id`, `target_user_id`, `entity_type`, `entity_id`, `date_from`, `date_to`) and paging. Each entry includes compact actor and target references, and `entity: {type, id, name}` for supplier / customer / production batch / order / material / preparation entries (the record's current name, or the batch / order / preparation code, falling back to the logged one).

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
  - `setWebhook` is only called when something changed: the URL, the allowed update types, the secret, `TELEGRAM_DROP_PENDING_UPDATES` or `MINI_APP_URL` (the menu button's target).
  - Telegram never returns the secret, so a fingerprint of what was last registered is kept in `app_settings`.
  - Registration also sets the bot's command list (`/start`, `/lang`; no attendance commands) and its **menu button**: a `web_app` button **បើកកម្មវិធី** → `MINI_APP_URL` (the default menu button when it isn't HTTPS). Polling mode sets both at startup.
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
| `/start` | **Binds** the sender's Telegram account first when no active user is bound to its id yet: the active user with the same normalized Telegram username and no binding (exactly the Mini App rule, §1.2) gets `telegram_user_id`, audited as `auth.telegram_bound` with `details.via = "bot_start"`, and the greeting ends with *"✅ Your Telegram account is now linked. Alerts will be sent here."* An account already bound to another id is never rebound, and the superadmin is never bound this way (it uses its link, §7.5). Then it greets the user in their language, with a hint in the other language, and shows an **Open app** WebApp button pointing to `MINI_APP_URL`. For a linked **tracked employee** (active staff or supervisor) a second button sits next to it: **🕒 វត្តមាន / Attendance** → the check screen `/attendance/check` (§22.12). |
| `/start link_<token>` | The superadmin's one-time link (§7.5): binds the sender's Telegram account and replies *"✅ Telegram linked."* An unknown, expired or used token, or a Telegram account already bound to another active user, gets one neutral reply (*"This link can't be used. Create a new one in the app."*). |
| `/lang` | Toggles the bot language between Khmer and English. If the Telegram account is linked to a user, their app language is updated too. |

- **Menu button per chat:** `/start` and `/lang` set this chat's menu button in its language (**បើកកម្មវិធី** / **Open app**); failures are only logged.
- **Attendance** (§22): no commands; the `/start` Attendance button, the menu button, and the check-in / check-out confirmations and scheduler reminders (after the commit, with the check-screen button).
- **Which language the bot uses:** the linked user's `language` first, then `bot_prefs`, then Khmer.
- **If `MINI_APP_URL` isn't HTTPS or is empty,** the bot says the app isn't configured instead of showing the button.
- **If `TELEGRAM_BOT_TOKEN` is empty,** the bot is disabled. The webhook endpoint returns 404, and the polling process logs a warning and exits cleanly.
- **Commands behave the same in webhook and polling mode.** Both use the same handlers (`app/bot/setup.py`).
- **Production alerts** (§16) are sent by the API, not by a command: after the Finish that caused them, in the recipient's language.

### 7.5 Superadmin Telegram link

The superadmin has no Telegram username, so it can't be matched on first Mini App sign-in like everyone else. To receive production alerts it links its Telegram account explicitly:

1. `POST /me/telegram-link` (**superadmin only**, `require_role` → `FORBIDDEN_ROLE` for anyone else) creates a random one-time token, stores only its SHA-256 hash (`telegram_link_tokens`) with a **10-minute** expiry, and returns `{url: "https://t.me/<bot>?start=link_<token>", expires_at}`. The bot username comes from `getMe` (cached per process). Without a bot token (or if Telegram can't be reached) → `503 TELEGRAM_NOT_CONFIGURED`.
2. Opening the link and tapping **Start** sends `/start link_<token>`. A valid, unexpired, unused token sets the superadmin's `telegram_user_id` to the sender's id, marks the token (and any other unused one of that user) used and writes `profile.telegram_link`. The reply names no role.
3. `DELETE /me/telegram-link` (superadmin only) clears `telegram_user_id` (`profile.telegram_unlink`); `204` also when nothing was linked.

- `/auth/me` shows the state as `user.telegram_linked`. Every user response has it (`GET /users`, `GET /users/{id}`, …, within the viewer's scope; the superadmin stays hidden as usual), so managers see who hasn't linked yet. The Telegram id itself is never in any response.
- **Mini App sign-in:** Telegram sign-in matches users by their bound Telegram id first, so once linked, opening the Mini App from that Telegram account **signs the superadmin in** too (it still has no username, so nothing else changes). This is intended: the linked account is the superadmin's own.

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
| Telegram | `TELEGRAM_NOT_CONFIGURED` (503; also: linking without a bot token, sending a delivery note with the bot off), `INVALID_TELEGRAM_DATA`, `TELEGRAM_DATA_EXPIRED`, `USER_NOT_REGISTERED`, `TELEGRAM_NOT_LINKED` (409: sending a delivery note to your Telegram without a linked account; open the Mini App from the bot once), `TELEGRAM_SEND_FAILED` (502: Telegram refused the document or couldn't be reached; nothing counted) |
| Authorization | `FORBIDDEN_SCOPE`, `FORBIDDEN_ROLE`, `MISSING_PERMISSION`, `PERMISSION_NOT_HELD` (also: a supervisor setting a staff level above its own access, `details = {feature, level}`), `PERMISSION_NOT_ASSIGNABLE`, `PERMISSION_NOT_FOUND`, `PERMISSION_GRANT_RESTRICTED` (kept; never reachable by non-superadmins today) |
| Access levels | `FEATURE_NOT_FOUND` (404), `FEATURE_NOT_APPLICABLE` (422) |
| Users | `USER_NOT_FOUND`, `USER_INACTIVE`, `INVALID_TELEGRAM_USERNAME`, `DUPLICATE_TELEGRAM_USERNAME`, `ROLE_LIMIT_REACHED` (409, `details = {role, limit, active}`), `GM_ALREADY_EXISTS` (kept, no longer raised), `POSITION_REQUIRED`, `POSITION_NOT_ALLOWED` |
| Suppliers & customers | `SUPPLIER_NOT_FOUND`, `CUSTOMER_NOT_FOUND`, `DUPLICATE_PHONE` (409), `INVALID_PHONE` (422, `details.min_digits` / `max_digits`), `SUPPLIER_INACTIVE` (422, production step 1 finish) |
| Production | `PRODUCTION_NOT_FOUND` (404), `PRODUCTION_STEP_NOT_READY` (409), `PRODUCTION_STEP_FINISHED` (409), `PRODUCTION_STEP_LOCKED` (409; no longer raised, kept for compatibility), `PRODUCTION_BALANCE_MISMATCH` (422, `details.wings` / `details.thighs`), `PRODUCTION_CONFLICT` (409, `details.batch`), `PRODUCTION_CANCELLED` (409), `PRODUCTION_COMPLETED` (409) |
| Packaging plan | `PRODUCTION_PLAN_REQUIRED` (409: step 3 save / finish while the plan isn't confirmed), `PRODUCTION_PLAN_LOCKED` (409: plan change after step 3 is finished), `PRODUCTION_PLAN_EXCEEDS_OUTPUT` (422, `details.wings` / `details.thighs`: `{available, planned}`), `PRODUCTION_PLAN_COMMENT_REQUIRED` (422, `details.planned` / `details.actual`: `{big, small}`; when the satay sachets differ too, also `details.sachets` and `details.reasons = ["plan", "sachets"]`), `PRODUCTION_SACHET_COMMENT_REQUIRED` (422: satay sachets used differ from the packs and there's no comment; `details = {"4": {expected, used}, "2": {expected, used}}`, §14.1) |
| Notifications | `NOTIFICATION_NOT_FOUND` (404: unknown, or someone else's) |
| Orders | `ORDER_NOT_FOUND` (404), `ORDER_CONFLICT` (409, `details.order`: the current order), `ORDER_INVALID_STATUS` (409, `details.status`: the action isn't allowed in the order's status), `ORDER_CONTAINERS_REQUIRED` (422: Delivered without every returnable box exactly once; `details.box_ids` = the missing boxes, `details.extra_box_ids` = boxes sent that aren't returnable, unknown or listed twice), `ORDER_CONTAINER_STATE` (409: marking a box returned later that isn't recorded as not returned; `details.container_status`, `details.status`), `CUSTOMER_INACTIVE` (422: the chosen customer is deactivated), `CUSTOMER_NOT_FOUND` (422 on orders), `INVALID_PHONE` (422: a direct order's phone), `DRIVER_NOT_ALLOWED` (422: the driver isn't an active staff member or supervisor) |
| Documents | `DOCUMENT_UNAVAILABLE` (503: WeasyPrint's system libraries are missing, or rendering took longer than 20 s; nothing counted) |
| Production guard | `PRODUCTION_STOCK_ALREADY_USED` (409: a reopen / cancel would take back stock that already left in orders; `details = {items: [{item_code, name_en, name_km, remaining_count, remaining_kg, needed_count, needed_kg, orders}], orders}`, §18.10) |
| Inventory | `INVENTORY_INSUFFICIENT` (409: a balance would go below zero; `details.items` = `[{item_code, name_en, name_km, available_count, available_kg, needed_count, needed_kg}]`; raised by Finish, reopen and cancel as a safeguard, and by **Delivering** an order when its totals are above the stock, §19), `INVENTORY_ITEM_NOT_FOUND` (404), `INVENTORY_ITEM_PRODUCTION_ONLY` (409: setting an item's value directly, for everyone, `details.item_code`; materials also `details.use = "material_add_remove"`) |
| Materials | `MATERIAL_NOT_FOUND` (404), `MATERIAL_UNIT_LOCKED` (409: to / from count or m² after the first movement), `MATERIAL_ARCHIVED` (409: stock change on an archived material), `MATERIAL_SYSTEM_LOCKED` (409: archiving Marinade sauce or switching it to count or m²), `DUPLICATE_MATERIAL_NAME` (409, `details.fields`) |
| Preparations | `PREPARATION_NOT_FOUND` (404), `PREPARATION_CONFLICT` (409, `details.preparation`: the current preparation), `PREPARATION_CANCELLED` (409: any change to a cancelled preparation), `PREPARATION_INVALID_STATUS` (409, `details.status`: saving or finishing a finished one, reopening a draft); also `VALIDATION_ERROR` (values, line kind, a non-preparable material), `MATERIAL_ARCHIVED` (409 at Finish, `details` names the material) and `INVENTORY_INSUFFICIENT` (§18.3) |
| Attendance | `ATTENDANCE_NOT_REQUIRED` (403; 422 when correcting someone who isn't tracked), `ATTENDANCE_WORKPLACE_NOT_SET` (409), `ATTENDANCE_TOO_EARLY` (409, `details.opens_at`, `shift_code`), `ATTENDANCE_NO_SHIFT_NOW` (409, `next_opens_at`, `next_shift_code`), `ATTENDANCE_CHECKIN_CLOSED` (409, `shift_code`, `closed_at`, `next_opens_at`), `ATTENDANCE_CHECKOUT_TOO_EARLY` (409, `opens_at`, `shift_code`), `ATTENDANCE_CHECKOUT_CLOSED` (409, `shift_code`, `closed_at`), `ATTENDANCE_ALREADY_CHECKED_IN`, `ATTENDANCE_NOT_CHECKED_IN`, `ATTENDANCE_ALREADY_CHECKED_OUT` (409, `shift_code`), `ATTENDANCE_TOO_FAR` (422, `distance_m`, `radius_m`), `ATTENDANCE_RECORD_NOT_FOUND` (404), `ATTENDANCE_RECORD_EXISTS` (409), `ATTENDANCE_WORKPLACE_NOT_FOUND` (404), `ATTENDANCE_DAY_OFF` (409, `reason`: `holiday` \| `weekday`, `holidays` (`name_km`, `name_en`), `next_opens_at`, `next_shift_code`), `ATTENDANCE_HOLIDAY_NOT_FOUND` (404), `ATTENDANCE_SCHEDULE_VERSION_NOT_FOUND` (404), `ATTENDANCE_SCHEDULE_VERSION_IN_EFFECT` (409: only upcoming versions can be deleted), `ATTENDANCE_NOT_STARTED` (409, `details.start_date`: before the employee's attendance start date), `ATTENDANCE_START_LOCKED` (409, `details.start_date`: the start date has arrived and can't be edited); a start date in the past → `VALIDATION_ERROR` with `details.code = ATTENDANCE_START_IN_PAST`; requests (§22.15): `ATTENDANCE_REQUEST_WINDOW_CLOSED` (409, `details.opens`, `closes`: the month hasn't ended or the deadline has passed), `ATTENDANCE_REQUEST_EXISTS` (409, one per month, also after a rejection), `ATTENDANCE_REQUEST_NOT_NEEDED` (409, `details.missing_minutes`: under an hour), `ATTENDANCE_REQUEST_SPLIT_MISMATCH` (422, `details.expected`, `given`), `ATTENDANCE_REQUEST_NOT_FOUND` (404), `ATTENDANCE_REQUEST_NOT_PENDING` (409, `details.status`), `ATTENDANCE_MONTH_LOCKED` (409, `details.year`, `month`: correcting or adding a record in a month locked by a pending or approved request); workplaces: `WORKPLACE_IN_USE` (409, `details.employees`), `WORKPLACE_IS_DEFAULT` (409), `WORKPLACE_NAME_TAKEN` (409, `name`), `WORKPLACE_ARCHIVED` (409); impossible shift times or rules, a past `effective_from`, a holiday longer than 31 days or ending before it starts, or a future / invalid summary period → `VALIDATION_ERROR` (`details.fields`) |
| Generic | `VALIDATION_ERROR` (with `details.fields`; also a logo that isn't a PNG / JPEG or is over 500 kB, `loc = ["body", "file"]`), `NOT_FOUND` (also: `GET /settings/business/logo` without a logo), `METHOD_NOT_ALLOWED`, `HTTP_ERROR` |

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
| GET | `/me/telegram-bot` | signed in: `{url: "https://t.me/<bot>"}` (the bot username from `getMe`, cached), where pressing Start links the account (§7.4); no bot token or Telegram unreachable → `503 TELEGRAM_NOT_CONFIGURED` |
| POST, DELETE | `/me/telegram-link` | role: superadmin (§7.5) |
| GET | `/notifications` | signed in (own only) |
| POST | `/notifications/{id}/read` | signed in (own only) |
| POST | `/notifications/read-all` | signed in (own only) |
| GET | `/users` | `users.view` |
| GET | `/users/positions` | `users.view` (scoped) |
| GET | `/users/role-capacity` | `users.view` or `users.create` (roles the actor manages) |
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
| GET | `/users/{id}/features` | `permissions.grant` or `users.manage_access` + scope |
| PUT | `/users/{id}/features/{feature}` | `permissions.grant` or `users.manage_access` + scope + level rules and cap (§12.3) |
| GET | `/audit-logs` | `audit.view` (superadmin implicit; a GM with Audit log) |
| GET | `/settings/role-limits` | role: superadmin |
| PUT | `/settings/role-limits/{role}` | role: superadmin |
| GET, PUT | `/settings/business` | `settings.business_info` (superadmin implicit; a GM with Business info) |
| GET, PUT, DELETE | `/settings/business/logo` | `settings.business_info` (PUT: multipart `file`) |
| GET | `/settings/business/preview.pdf` | `settings.business_info` |
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
| GET | `/production-plans` | `production_plan.view` |
| GET | `/production-plans/{batch_id}` | `production_plan.view` |
| PATCH | `/production-plans/{batch_id}` | `production_plan.manage` |
| POST | `/production-plans/{batch_id}/confirm` | `production_plan.manage` |
| GET | `/inventory` | `inventory.view` |
| GET | `/inventory/items/{item_code}` | `inventory.view` |
| GET | `/inventory/movements` | `inventory.history` (filters incl. `order_id`, `preparation_id`) |
| POST | `/inventory/items/{item_code}/set` | `inventory.view`; every item → `409 INVENTORY_ITEM_PRODUCTION_ONLY` (§18.5) |
| GET | `/inventory/materials` | `inventory.view` (`include_archived` only with `inventory.materials_manage`) |
| POST | `/inventory/materials` | `inventory.materials_manage` |
| PATCH | `/inventory/materials/{id}` | `inventory.materials_manage` |
| POST | `/inventory/materials/{id}/archive` · `/restore` | `inventory.materials_manage` |
| POST | `/inventory/materials/{id}/add` · `/remove` | `inventory.materials_stock` |
| GET | `/orders` | `orders.view` |
| GET | `/orders/stats` | `orders.view` |
| GET | `/orders/customer-options` · `/orders/driver-options` · `/orders/available-stock` | `orders.create` or `orders.update` |
| POST | `/orders` | `orders.create` |
| GET | `/orders/{id}` | `orders.view` |
| PATCH | `/orders/{id}` | `orders.update` (Created only) |
| POST | `/orders/{id}/cancel` | `orders.cancel` (Created only) |
| POST | `/orders/{id}/delivering` · `/orders/{id}/delivered` | `orders.create` |
| POST | `/orders/{id}/returns/review` | `orders.review_returns` |
| POST | `/orders/{id}/boxes/{box_id}/container-returned` | `orders.containers` (a box recorded as not returned; doesn't change the order's `version`) |
| GET | `/orders/{id}/document.pdf` | `orders.view` (any status) |
| GET | `/orders/delivery-note/supplier` | `orders.export_delivery_note` (the business name, address and phone for the Excel delivery note; no Business info access needed) |
| POST | `/orders/{id}/document/send-telegram` | `orders.view` (to the requester's own chat) |
| GET | `/preparations` | `preparation.view` |
| GET | `/preparations/stats` | `preparation.view` |
| GET | `/preparations/material-options` | `preparation.create` |
| POST | `/preparations` | `preparation.create` |
| GET | `/preparations/{id}` | `preparation.view` |
| PATCH | `/preparations/{id}` | `preparation.create` (drafts) |
| POST | `/preparations/{id}/finish` | `preparation.create` |
| POST | `/preparations/{id}/reopen` | `preparation.update` |
| POST | `/preparations/{id}/cancel` | `preparation.cancel` |
| GET | `/attendance/me/today` | tracked employee (active staff, supervisor) |
| POST | `/attendance/check-in`, `/attendance/check-out` | tracked employee |
| GET | `/attendance/me/summary` | tracked employee |
| GET | `/attendance/day` | `attendance.view` |
| GET | `/attendance/users/{id}/summary` | `attendance.view` + scope |
| PATCH | `/attendance/records/{id}` | `attendance.correct` + scope |
| POST | `/attendance/records` | `attendance.correct` + scope |
| GET | `/attendance/requests/me` | tracked employee |
| POST | `/attendance/requests` | tracked employee |
| GET | `/attendance/requests`, `/attendance/settings/requests` | `attendance.requests_review` + scope |
| GET | `/attendance/requests/{id}` | the employee, or `attendance.requests_review` + scope |
| POST | `/attendance/requests/{id}/approve`, `/attendance/requests/{id}/reject` | `attendance.requests_review` + scope |
| PUT | `/attendance/settings/requests` | superadmin |
| GET | `/attendance/workplace-options` | `users.view` or any workplace permission |
| GET | `/attendance/workplaces`, `/attendance/workplaces/{id}` | `attendance.workplace_view`, `workplace_update` or `workplace_manage` |
| POST | `/attendance/workplaces`, `/attendance/workplaces/{id}/restore` | `attendance.workplace_manage` |
| PATCH | `/attendance/workplaces/{id}` | `attendance.workplace_update`; `is_default` also needs `attendance.workplace_manage` |
| DELETE | `/attendance/workplaces/{id}` | `attendance.workplace_manage` |
| GET | `/attendance/scheduling`, `/attendance/calendar`, `/attendance/holidays`, `/attendance/holidays/{id}` | `attendance.view` or `attendance.scheduling` |
| PUT | `/attendance/scheduling/weekdays`, `/attendance/scheduling/shifts` | `attendance.scheduling` |
| DELETE | `/attendance/scheduling/versions/{id}` | `attendance.scheduling` |
| POST, PATCH, DELETE | `/attendance/holidays`, `/attendance/holidays/copy`, `/attendance/holidays/{id}` | `attendance.scheduling` |
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
- Staff have nothing by default. A general manager sets the Suppliers / Customers feature: **View only** lets them list and open records; **Full access** also lets them add, edit and deactivate (§12).

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

How general managers (and, for staff, supervisors with Staff access) give access. Each feature switches a group of detailed permissions at once: **Off**, **View only**, **Record** (only features that define it) or **Full access**.

### 12.1 Registry

`FEATURES` in `app/permissions/registry.py`. Each feature has `code`, `menu` (`workstation` | `attendance` | `settings`, listed in that order in `MENUS`; startup validation rejects any other value), names and descriptions in Khmer and English, `applies_to` (roles it can be set for) and `levels`: an ordered mapping level → the exact permission codes of that level, always starting with `off` → none.

| Feature | Menu | Applies to | View only | Record | Full access |
|---|---|---|---|---|---|
| `suppliers` | workstation | GM, supervisor, staff | `suppliers.view` | — | `suppliers.view/create/update/delete` |
| `customers` | workstation | GM, supervisor, staff | `customers.view` | — | `customers.view/create/update/delete` |
| `production` | workstation | GM, supervisor, staff | `production.view` | `production.view/create` | `production.view/create/update` |
| `production_plan` | workstation | GM, supervisor | `production_plan.view` | — | `production_plan.view/manage` |
| `inventory` | workstation | GM, supervisor, staff | `inventory.view` | `inventory.view/materials_stock` | — |
| `inventory_history` | workstation | GM, supervisor | `inventory.history` | — | — |
| `inventory_materials` | workstation | GM, supervisor | — | — | `inventory.materials_manage` |
| `orders` | workstation | GM, supervisor, staff | `orders.view` | `orders.view/create` | — |
| `order_management` | workstation | GM, supervisor | — | — | `orders.update/cancel` |
| `order_returns` | workstation | GM, supervisor | — | — | `orders.review_returns` |
| `order_export` | workstation | GM, supervisor, staff | — | — | `orders.export_delivery_note` |
| `order_containers` | workstation | GM, supervisor, staff | — | — | `orders.containers` |
| `preparation` | workstation | GM, supervisor, staff | `preparation.view` | `preparation.view/create` | — |
| `preparation_management` | workstation | GM, supervisor | — | — | `preparation.update/cancel` |
| `attendance` | attendance | GM, supervisor | `attendance.view` | — | — |
| `attendance_corrections` | attendance | GM, supervisor | — | — | `attendance.correct` |
| `attendance_workplace` | attendance | **GM** | `attendance.workplace_view` | `attendance.workplace_view/update` | `attendance.workplace_view/update/manage` |
| `attendance_scheduling` | attendance | GM, supervisor (grantor must hold it) | — | — | `attendance.scheduling` |
| `attendance_requests` | attendance | GM, supervisor | — | — | `attendance.requests_review` |
| `staff_management` | settings | GM, supervisor | `users.view` | `users.view/create` | `users.view/create/update` |
| `staff_access` | settings | supervisor | — | — | `users.manage_access` |
| `business_info` | settings | **GM** | — | — | `settings.business_info` |
| `audit_log` | settings | **GM** | `audit.view` | — | — |

**Staff management:** *View only* = see staff; *Record* = also add staff; *Full access* = also edit their info (name, phone, Telegram username, position, language). Deactivating stays GM-only (`users.delete`). A GM with default permissions still reads as Full access.

**Business info** (GM only, §20): *Full access* = edit the business info printed on delivery notes. It applies only to the general manager, so only the superadmin can turn it on; default Off.

**Audit log** (GM only, §6): *View only* = open the audit log, filtered as in §13. Only the superadmin can turn it on; default Off. Switching it off removes access at once.

**Attendance** (§22.11): *View only* = see each day's attendance of the people in scope (and Scheduling, read-only); **Attendance corrections** *Full access* = fix and add records. **Workplaces** applies to the GM only, so only the superadmin sets it (default View only). **Attendance scheduling** *Full access* = manage tracked weekdays, holidays, shift times and rules (§22.14); grantor must hold it: the superadmin turns it on for a GM, and a GM holding it can give it to supervisors (defaults Off for both).

**Staff access** (supervisors only): *Full access* = may set the Suppliers / Customers / Production levels of staff, up to the supervisor's own levels (§12.3); *Off* = no Access tab.

**Record** in Production means "can start batches and fill in steps, but can't reopen finished steps". **Full access** in Production adds reopening finished steps; cancelling batches (`production.delete`) is GM-only and outside the levels.

**Feature levels for general managers.** Every feature also applies to the GM, but only the superadmin manages the GM (role scope), so only the superadmin sets them, on the GM's Access tab. The GM never sees or changes its own levels (`FORBIDDEN_SCOPE` on `/users/{own id}/features`). A GM with default permissions reads as **Full access** everywhere. The GM-only powers (`users.delete`, `users.reset_password`, `permissions.grant`, `production.delete`) are not in any feature and stay detailed permissions, set by the superadmin on **Permissions (advanced)**; level changes never touch them. Note that Staff management below *Full access* takes creating / editing users (or, at *Off*, the Users list) away from the GM, and revoking `permissions.grant` removes the GM's Access tab for everyone it manages.

- `users.delete`, `users.reset_password` and `permissions.grant` belong to **no** feature: they stay general-manager-only and are managed as detailed permissions by the superadmin.
- **Startup validation** (`validate_features`, at import and in bootstrap): every code a feature uses exists, is assignable to every role in `applies_to`, and has no `grantable_by`; the first level is `off` with no codes; levels are unique and follow the order `off` → `view` → `record` → `full` (`LEVELS`), where any after `off` may be omitted (production and staff management use `record`; staff access has only `off` and `full`). A mismatch stops the API from starting.
- **Orders:** *View only* = see orders; *Record* = also create them, start delivery, mark them delivered and record returns (Orders has no Full access level). **Order management** *Full access* = edit and cancel Created orders. **Order returns** *Full access* = review returns and **receive the order alerts**. A GM with default permissions reads as Orders *Record*, management and returns *Full access*. A supervisor with Staff access can give staff Orders only up to its own Orders level. **Order containers** *Full access* = mark boxes that weren't given back at delivery as returned later (§19.7); defaults GM Full, supervisors and staff Off (a supervisor with Staff access can give it to staff only while holding it).
- **Inventory:** *View only* = see stock, wasted items and materials; *Record* = also add and remove the stock of materials (with a reason to remove). **Inventory materials** *Full access* = create, edit, archive and restore materials. Defaults: GM Record + Full; supervisors Record + Off; staff Off (a supervisor with Staff access can give staff up to its own Inventory level).
- **Preparation:** *View only* = see preparations; *Record* = also create, fill in and finish them (Preparation has no Full access level). **Preparation management** *Full access* = reopen and cancel preparations and **receive the preparation alerts**. Defaults: GM Record + Full; supervisors Record + Off; staff Off (a supervisor with Staff access can give staff Preparation up to its own level; management doesn't apply to staff).
- **Production plan:** *View only* = see plans and receive the production alerts; *Full access* = also set and confirm plans. Supervisors start at *Off*; the GM starts at *Full access*.

### 12.2 Current level

A user's level for a feature is the level whose code set **exactly equals** the user's effective permissions restricted to that feature's codes. No exact match (e.g. only `suppliers.view` + `suppliers.update`, set by the superadmin) → `custom`.

### 12.3 Endpoints

Two kinds of grantor:

- **General manager and superadmin (`permissions.grant`): any level of any feature** that applies to a user they manage (supervisors and staff; the superadmin also the GM). Unlike detailed grants, their own feature permissions don't matter here: the Access layer is theirs. (Detailed permissions, §5.4, stay superadmin-only.)
- **Supervisor with Staff access (`users.manage_access`, without `permissions.grant`):** only staff (normal scope: another supervisor or a GM → `FORBIDDEN_SCOPE`), and **capped**: every code of the target level must be in the supervisor's own effective permissions, i.e. what a GM or the superadmin gave them. Setting `off`, or any level within its own, is allowed, including lowering a level a GM set higher.
- **Grantor must hold it** (`FeatureDef.grantor_must_hold`: `inventory_history` and `attendance_scheduling`): such a feature exists only for grantors who hold every code of it. The superadmin always does; a general manager only while holding it. For anyone else it's left out of `GET /users/{id}/features`, `PUT` answers `404 FEATURE_NOT_FOUND` (at the "feature exists" step, before the target-role check, so its existence isn't revealed), and its `feature.set` audit entries are hidden from them (§13). No cascade: removing it from the grantor leaves the levels they set.
- **No cascade:** when a GM later lowers a supervisor's access, staff levels that supervisor set earlier are **not** changed (like revoking, §5.4); the supervisor just can't raise them again.

`GET /users/{id}/features` (`permissions.grant` or `users.manage_access` + scope) returns the features that apply to the target's role, grouped by menu (workstation, attendance, then settings; empty menus omitted). Each feature: `code`, `menu`, names/descriptions, `levels` (in order; each `{level, allowed}`, where `allowed` is false when the level is above a supervisor's own access, always true for the GM and the superadmin), `current_level` (`off` / `view` / `record` / `full` / `custom`) and `can_edit` (the actor manages access and the target, and the target is active). Nothing in the response to a supervisor describes a GM or the superadmin (§13).

`PUT /users/{id}/features/{feature}` with `{ "level": "off" | "view" | "record" | "full" }` (one of the feature's levels) checks, in order:

1. `permissions.grant` or `users.manage_access` (route guard) → `MISSING_PERMISSION` (`details.required` lists both)
2. the target exists and is visible to the actor (§13) → `USER_NOT_FOUND`; the target is in scope → `FORBIDDEN_SCOPE`
3. the feature exists, and for a `grantor_must_hold` feature the actor holds it → `FEATURE_NOT_FOUND`
4. it applies to the target's role → `FEATURE_NOT_APPLICABLE`
5. the level exists for the feature → `VALIDATION_ERROR`
6. supervisors only: every code of the level is in the actor's effective permissions → `403 PERMISSION_NOT_HELD`, `details = {feature, level}`
7. the target is active → `USER_INACTIVE`

It then applies a **diff within the feature's codes only** (grants the missing codes with `granted_by` = actor, revokes the extra ones) in one transaction; the user's other permissions are untouched. Setting `custom` → a level overwrites it. Setting the current level again is a no-op: `200`, nothing written. Each change writes one `feature.set` audit entry (§6).

The superadmin can use these endpoints too. Adding and editing staff info stay separate (`users.create` / `users.update`, §4): Staff access alone doesn't allow them.

---

## 13. Visibility and redaction

**The superadmin is invisible to everyone else.** Nothing general managers, supervisors or staff can reach reveals the superadmin's id, login name, full name or role.

- **User references** in every response use one schema (`schemas.common.UserRef`: `id`, `full_name`, `role`, `telegram_username`, `is_system`). For a viewer who isn't the superadmin, a reference to the superadmin serializes as `{ "id": null, "full_name": "System", "role": null, "telegram_username": null, "is_system": true }`. This covers `created_by` on users (including the GM's own record in `/auth/me`) and on suppliers/customers, `updated_by`, and the audit log's `actor` / `target`. It is applied at serialization time (`services/redaction.py`), so new endpoints are covered as long as they use `UserRef`. Without a known viewer it fails closed (hidden).
- **Features a grantor doesn't hold** (`grantor_must_hold`, e.g. Inventory history, §12.3) don't exist for that grantor: left out of `GET /users/{id}/features`, `404 FEATURE_NOT_FOUND` on PUT (not a permission error, which would reveal it), and their `feature.set` entries are left out of that GM's audit log (`details.feature`).
- **GM feature levels** are visible only to the superadmin: only it manages the GM, and `feature.set` entries it makes are left out of the GM's audit log like everything else it does.
- **Lookups by id:** every per-user endpoint (`GET/PATCH /users/{id}`, deactivate, reactivate, reset-password, features, …) answers `404 USER_NOT_FOUND` when a non-superadmin asks for the superadmin, not `403 FORBIDDEN_SCOPE`, which would confirm it exists.
- **Audit log for general managers** (only with `audit.view`, §6): left out are every entry **made by** the superadmin, every entry whose **target** is the superadmin (e.g. its sign-ins), and all `permission.grant` / `permission.revoke` entries (incl. `default_backfill`); the GM sees `feature.set` instead. Entries without an actor (failed sign-ins, lockouts) stay. The `actor_id` / `target_user_id` filters never match the superadmin.
- **Wording:** no error message, detail or schema text reachable by non-superadmins names the superadmin or lists roles. `FORBIDDEN_ROLE` carries no `allowed_roles`; `FORBIDDEN_SCOPE` doesn't name the role; `422` messages for enum/literal fields don't list the allowed values.
- **API docs** (`/docs`, `/redoc`, `/openapi.json`) describe every role, so they are served only when `API_DOCS_ENABLED=true`, or when it is unset and `ENVIRONMENT=development` (the default). Set `ENVIRONMENT=production` in production.
- **UI:** one build for everyone. The superadmin's role label is "System" / "ប្រព័ន្ធ", like the API's redacted references; its extra screens are runtime checks. Their code is in the bundle (visible in browser dev tools), but they never receive superadmin data because the API redacts it.
- **Notifications and plans:** a notification stores the actor's id and serializes it as a `UserRef` for the recipient reading it, so a step finished by the superadmin reads as "System" to everyone else; the Telegram texts never name the actor. Plan `confirmed_by` / `updated_by` are `UserRef`s too.
- **Orders:** every user reference on an order (`created_by`, `driver`, `delivering_by`, `delivered_by`, `returns_reviewed_by`, `cancelled_by`, `updated_by`, each return's `reviewed_by`, each box's `container_recorded_by` / `container_returned_later_by`) is a `UserRef`; the order routes are in the redaction and superset sweeps, with orders the superadmin created and cancelled. Driver options list only active staff and supervisors.
- **Preparations:** `created_by`, `updated_by`, `finished_by`, `cancelled_by` are `UserRef`s; the routes are in the redaction and superset sweeps, with preparations the superadmin created, finished (alerting the GM, read as "System") and cancelled.
- **Attendance:** `corrected_by` on records, `updated_by` on the workplace and the rules are `UserRef`s; the day view's rows are employees (never the superadmin, who isn't tracked), and the superadmin's id as `user_id` of a new record is `USER_NOT_FOUND`. The routes are in the redaction and superset sweeps, with a record the superadmin added and corrected and a workplace and rules it changed.
- **Delivery notes** (§19.6) are rendered from the order as serialized for the requester, so the name on them ("Prepared by") is redacted like any `UserRef`. The redaction sweep reads them as HTML (`html_documents` fixture) and checks the text.
- **Linked Telegram id:** the superadmin's (like everyone's) `telegram_user_id` is never serialized; responses only carry `telegram_linked`.
- **Tests:** `tests/test_redaction.py` calls every GET route (from the OpenAPI schema) plus key mutations as a GM, a supervisor and staff, over data the superadmin created, and fails if a body contains the superadmin's id, name or the word "superadmin". Its data includes a batch whose step 2 the superadmin finished and whose plan it confirmed (alerts for the GM and a supervisor with plan access).
- **Not covered (known):** five wrong passwords for the login name `superadmin` on the login page return "account locked", which reveals that the account exists.

---

## 14. Production

Production records one **batch** as it moves through three steps. Each step is saved as a **draft** while it's filled in (autosave) and locked by **Finish**. It appears under **Workstation → Production** (ផលិតកម្ម) in the UI.

```
New production → batch PR-YYYYMMDD-NNN
  Step 1 Intake (ការនាំចូល)         → Finish → import date (ថ្ងៃនាំចូល) recorded
  Step 2 Processing (ការផលិត)       → Finish → production date (ថ្ងៃផលិត) recorded   (only after step 1 is finished)
                                             → packaging plan created (pending) + alert "set the plan" (§15, §16)
  Packaging plan (ផែនការវេចខ្ចប់)    → filled in and confirmed (production_plan.manage)
  Step 3 Standardize (ការវេចខ្ចប់)   → Finish → packing date (ថ្ងៃវេចខ្ចប់) recorded   (only after step 2 is finished AND the plan is confirmed)
                                             → batch completed + alert "completed" / "completed, differs from plan"
```

The API step codes stay `raw-material`, `produced` and `standardize` (URLs, `steps`, audit details); only the displayed names changed.

### 14.1 Steps and fields

Weights are exact decimals (`NUMERIC`, `Decimal` in Python), accepted as JSON numbers or strings and **always returned as fixed-precision strings**: kg with 3 decimals (`"12.500"`), grams with 1 (`"350.0"`), square metres with 2 (`"12.50"`). Counts are whole numbers. Draft saves only check types and ≥ 0; Finish checks the rules below.

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
| `marinade_g` (ទឹកប្រឡាក់) | g | Finish: required, ≥ 0. On a tracked batch, **Finish takes it out of the Marinade sauce material** (§18.11): not enough → `409 INVENTORY_INSUFFICIENT` and step 2 stays a draft; reopen / cancel put it back. `0` moves nothing. |

**Step 3: Standardize**

| Field | Rule |
|---|---|
| `big_packages` | **4-Piece Packs** (កញ្ចប់ ៤ ដុំ): whole ≥ 0; 1 pack = 2 wings + 2 thighs |
| `small_packages` | **2-Piece Packs** (កញ្ចប់ ២ ដុំ): whole ≥ 0; 1 pack = 1 wing + 1 thigh |
| `rejected_wings`, `rejected_thighs` | whole ≥ 0 |
| Per by-product: `carry_kg` (carried forward), `rejected_kg` | Finish: required, ≥ 0 |
| `sachets_4_used`, `sachets_2_used` | **Satay sachets used** (សាតេកញ្ចប់): whole ≥ 0. One per pack by default: 4-piece sachets follow `big_packages`, 2-piece follow `small_packages` (below). |
| `sachets_4_manual`, `sachets_2_manual` | `false` (default, "auto"): the count follows its pack count; `true`: typed by hand and kept |
| `comment` | at most 1000 characters (trimmed; empty → null). Optional, **except when the packs differ from the plan or the sachets differ from the packs** (below). |

All of these (except the comment and the sachets) are required at Finish. The app prefills empty step 3 fields when the form opens (packs = the confirmed plan, rejected wings / thighs 0, each by-product carried forward whole with 0 rejected) and saves them through the normal draft PATCH; the API itself sets no defaults. The API field names stay `big_packages` / `small_packages`; only the displayed names changed.

**Satay sachets** (one per pack: **4-Piece Pack → 4-piece satay sachet**, **2-Piece Pack → 2-piece satay sachet**):

- **Drafts:** the step 3 PATCH accepts the four fields. While a size's `*_manual` is `false` (sent, or already stored) the server stores **the current pack count** and ignores a `*_used` value, so "auto" survives across devices and follows every pack change. With `*_manual: true` the sent `*_used` (or the stored value) is kept; sending `*_manual: false` resets it to the pack count. A manual count may be cleared (`null`).
- **Finish:** a `null` count defaults to its pack count. A count that differs from its pack count (higher or lower) needs the **same `comment`** as the plan rule: else `422 PRODUCTION_SACHET_COMMENT_REQUIRED` with `details = {"4": {expected, used}, "2": {expected, used}}`. **One comment covers both reasons**; when the packs also differ from the plan, `PRODUCTION_PLAN_COMMENT_REQUIRED` comes first and its `details` gain `sachets` and `reasons: ["plan", "sachets"]`.
- **Inventory** (tracked batches only, §18.2): Finish takes `sachets_4_used` out of `satay_sachet_4` and `sachets_2_used` out of `satay_sachet_2`; not enough → `409 INVENTORY_INSUFFICIENT` (item, available, needed) and step 3 stays a draft. Reopen gives them back. Untracked batches record the counts but never move sachets.
- **Responses:** `standardize` has the four fields, plus `sachet_stock = {"4": count, "2": count}` (what Finish takes from) for viewers with `production.create` while step 3 of a tracked, in-progress batch is a draft (`null` otherwise).
- **Audit:** `production.step_finish` of step 3 adds `sachets_4_used` / `sachets_2_used`.
- **Before sachets existed** (migration `0025`): every step 3 row got its pack counts, manual `false`; no movement was written for the past.

**Step 3 and the plan** (§15):

- Saving or finishing step 3 while the plan isn't `confirmed` → `409 PRODUCTION_PLAN_REQUIRED` (checked after the step state, before the version).
- At Finish, when `big_packages ≠ expected_big` **or** `small_packages ≠ expected_small`, a non-empty `comment` is required → else `422 PRODUCTION_PLAN_COMMENT_REQUIRED` with `details = {planned: {big, small}, actual: {big, small}}` (plus `sachets` / `reasons` when the sachets differ too, above). Checked after the piece balance, before the sachet rule and the stock.
- `standardize.plan_matches` in responses: `true` / `false` once both actual counts and both plan values exist, else `null`.

**Piece balance: enforced by the API at Finish** (`422 PRODUCTION_BALANCE_MISMATCH`):

```
2 × big + small + rejected_wings  = wings_count
2 × big + small + rejected_thighs = thighs_count
```

`details` has `{ wings: {expected, assigned, difference}, thighs: {…} }` (`difference` = expected − assigned).

**By-product balance: UI only, NOT enforced by the API.** For each by-product the UI requires `carry_kg + rejected_kg = produced kg` exactly before Finish is enabled. The API only checks that both values are present and ≥ 0, and accepts a batch whose by-products don't add up. This is deliberate (the rule may be relaxed later) and covered by a test. Inventory (§18) does limit it indirectly: step 3 takes carry + rejected kg out of the processed stock of all batches, so assigning more than that stock holds → `INVENTORY_INSUFFICIENT`.

**Catalogs** (`app/production/catalog.py`): the by-products (`code`, `name_en`, `name_km`, unit `kg`, display order) and material kinds (`chicken`: 2 wings and 2 thighs per chicken). Every batch response includes them (`catalog`) so the UI renders them. Adding a by-product or kind is a catalog entry, no migration.

### 14.2 Lifecycle

- Batch `status`: `in_progress` → `completed` (step 3 finished), or `cancelled`. `current_step` (1–3) is the step being worked on.
- Step `status`: `draft` → `finished`. A step's row exists once the previous one has been finished (`produced` / `standardize` are `null` in responses until then). A finished step is read-only: saving or finishing it again → `PRODUCTION_STEP_FINISHED`. Saving or finishing a step whose previous one isn't finished → `PRODUCTION_STEP_NOT_READY`.
- **Reopen** step N (`production.update`): allowed for any finished step of an in-progress or completed batch, whatever the later steps are. In one transaction (batch row locked), step N **and every later finished step** go back to `draft` (`finished_by` / `finished_at` and **the step's date** cleared; the next Finish records that new day); **all values are kept**; `current_step` becomes N; a completed batch goes back to `in_progress` (`completed_at = null`); `version` + 1. The later steps are then finished again in order (`PRODUCTION_STEP_NOT_READY` otherwise), which recomputes the step 2 counts from step 1 and re-checks the piece balance at step 3. **Reopening step 1 or 2 puts the packaging plan back to `pending`** (values kept, `confirmed_by/at` cleared), so step 3 waits until it's confirmed again; reopening step 3 keeps a confirmed plan (still editable until step 3 is finished again). Each step in a batch response carries `reopens_steps` (the steps editing it would put back to draft; `[]` when it isn't finished or the batch is cancelled) so the UI can warn. Reopening a step that is already a draft changes nothing. `PRODUCTION_STEP_LOCKED` is no longer raised.
- **Cancel** (`production.delete`, general manager and superadmin only): only `in_progress` batches (`PRODUCTION_COMPLETED` for completed ones), with a required reason (1–500 characters). A cancelled batch is read-only (`PRODUCTION_CANCELLED` for any change) and excluded from the figures.
- **Inventory side effects** (§18, tracked batches): **Finish** writes the step's stock movements, **reopen** reverses those of every step it sends back to draft (latest first), **cancel** reverses all of the batch's movements, in the same transaction. If a balance would go below zero the action is refused with `409 INVENTORY_INSUFFICIENT` and nothing changes. **Production guard:** a reopen or cancel needs the batch's **own** remaining stock to cover what it takes back; if its packs or packed by-products already left in orders → `409 PRODUCTION_STOCK_ALREADY_USED` with the items and the order codes (§18.10), and nothing changes. Batches created before inventory existed (`inventory_tracked = false`) never move stock.
- **Batch code** `PR-YYYYMMDD-NNN`: from the **creation day** in `BUSINESS_TIMEZONE` (e.g. 17:30 UTC on 30 Sep is already 1 Oct in Phnom Penh), numbered per day by a counter row (`production_batch_counters`, `INSERT … ON CONFLICT … RETURNING`), so concurrent creations get distinct numbers. The code never changes, whenever the steps are finished or reopened.

### 14.3 Drafts and versions

- `PATCH /production/{id}/raw-material` (`/produced`, `/standardize`) takes a **partial** body: only fields present are applied, `null` clears one. `produced` and `standardize` take `byproducts` as a map by item code (`{"liver": "0.4"}`, `{"liver": {"carry_kg": "0.3"}}`); unknown codes → `VALIDATION_ERROR`.
- Every write (draft save, finish, reopen, cancel) requires the batch **`version`** it's based on and increments it. A stale version → `409 PRODUCTION_CONFLICT` with the current batch in `details.batch`, so the client can show what changed and retry.
- Writes lock the batch row (`SELECT … FOR UPDATE`). Checks run in this order: not found, cancelled, step state, version, values.

### 14.4 Endpoints and figures

| Endpoint | Notes |
|---|---|
| `GET /production` | **Cancelled batches are left out** unless `include_cancelled=true` (then added to the chosen status) or `status=cancelled` (only them). Filters: `status` (`in_progress`, `completed`, `cancelled`, `all` = default: in progress + completed), `include_cancelled` (default `false`), `waiting_step` (`2` or `3`: in-progress batches whose previous steps are finished and that step isn't, for `3` only with a **confirmed** plan; `plan`: step 2 finished and the plan still **pending**), `date_from` / `date_to` (inclusive; a batch matches if **any** of its three step dates is in the range, or, while no step is finished, its **creation day**), `q` (batch code or supplier name). `sort`: `-date` (default), `date` — by the batch's **latest recorded step date**, falling back to its creation day, then by code — `code`, `-code`. Paging: 20 by default, at most 100. Items: `code`, `import_date`, `production_date`, `packaging_date` (null until recorded), `created_at`, `status`, `current_step`, `steps` (`pending` / `draft` / `finished` for steps 1–3), `supplier`, `quantity`, `created_by`. |
| `GET /production/stats` | `in_progress`; `completed_today` (completed since midnight, Cambodia time); `chickens_this_month` (quantity of finished step 1s whose **import date** is this month); `rejected_pieces_this_month` (rejected wings + thighs of finished step 3s whose **packing date** is this month). Months and days follow `BUSINESS_TIMEZONE`; cancelled batches are excluded. |
| `POST /production` | Creates the batch with a draft step 1; optional initial step 1 fields (no date). `201` with the batch. |
| `GET /production/{id}` | The batch, all steps, by-products, catalogs, `plan` (read-only: status, expected values, note, `confirmed_by/at`, `updated_by/at`; `null` before step 2 is finished), `plan_legacy` (`true` when step 2 was finished but there's no plan: batches finished before plans existed), `inventory_tracked` and `stock_changes` (§18.8; only for viewers with `inventory.history`, otherwise both keys are left out) and `computed` (`wings_count` / `thighs_count` from the current quantity, `yield_percent` = (wings kg + thighs kg) ÷ raw kg × 100, one decimal, or null). |
| `POST /production/{id}/{step}/finish` | `step` ∈ `raw-material`, `produced`, `standardize`; body `{version}`. Records the step's date (today, `BUSINESS_TIMEZONE`). Step 2 also creates the plan (or puts it back to pending); steps 2 and 3 create the alerts (§16). |
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

Defaults: general managers hold all four permissions (and reads as Full access; the superadmin can lower it), supervisors Full access, staff Off (§5.3). Anyone with `production.create` can fill in any in-progress batch, not only their own. Setting the packaging plan is a separate feature (§15): someone with Record can finish step 3, but only once a planner has confirmed the plan.

---

## 15. Packaging plan

Between step 2 and step 3 a planner decides how many **4-Piece Packs** (`expected_big`) and **2-Piece Packs** (`expected_small`) the batch should make. It appears under **Workstation → Production plan** (ផែនការវេចខ្ចប់) in the UI.

### 15.1 Data

`production_plans`, one row per batch (PK `batch_id`, cascade): `expected_big`, `expected_small` (whole ≥ 0, nullable), `note` (≤ 500, trimmed; empty → null), `status` (`pending` | `confirmed`), `confirmed_by/at`, `updated_by/at`. CHECK: a confirmed plan has both values.

### 15.2 Lifecycle

| Event | Plan |
|---|---|
| Step 2 finished the first time | created, `pending`, empty |
| Step 2 finished again (after a reopen) | back to `pending`, values kept |
| Step 1 or 2 reopened | back to `pending`, values kept → step 3 locked again |
| Step 3 reopened | stays `confirmed`, editable again |
| Step 3 finished (batch completed) | read-only → `409 PRODUCTION_PLAN_LOCKED` |
| Batch cancelled | read-only → `409 PRODUCTION_CANCELLED` |

- Step 3's row is still created when step 2 is finished, but it can't be saved or finished until the plan is `confirmed` (`PRODUCTION_PLAN_REQUIRED`).
- **Before plans existed:** the migration gave a `pending` plan to every in-progress batch whose step 2 was finished (their step 3 waits for it). Completed and cancelled batches got none: they answer `plan: null`, `plan_legacy: true`, and no alerts were sent for them. Reopening any step of such a batch creates its first plan, `pending`, pre-filled with its current packs.

### 15.3 Rules

- **Pieces:** a plan uses `2 × expected_big + expected_small` wings and as many thighs; that must be ≤ `wings_count` **and** ≤ `thighs_count` of step 2 → else `422 PRODUCTION_PLAN_EXCEEDS_OUTPUT` with `details = {wings: {available, planned}, thighs: {available, planned}}`. Checked on save (when both values are set) and on confirm.
- **Confirm** needs both values → else `VALIDATION_ERROR` (`details.fields` locations `["plan", "expected_big"]` / `["plan", "expected_small"]`).
- **Editing a confirmed plan** (step 3 not finished) keeps it confirmed; `updated_by/at` change. A confirmed plan can't lose a value (`null` → `VALIDATION_ERROR`).
- **Step 2 must be finished:** while it is a draft again after a reopen, saving or confirming → `409 PRODUCTION_STEP_NOT_READY` (the counts may still change).
- **Satay sachets (information only):** the detail's `sachets` compares what the plan needs (one per pack: `expected_big` 4-piece, `expected_small` 2-piece sachets) with the stock: `{needed: {"4", "2"}, in_stock: {"4", "2"}, short: {"4", "2"}}` (`short` = needed − in stock when positive, else 0). `null` until both expected counts are set, for untracked batches, and once step 3 is finished or the batch is cancelled. Confirming is allowed even when short: the stock is enforced at step 3 Finish.
- **Concurrency:** every plan write locks the batch row and uses the **batch `version`** (stale → `409 PRODUCTION_CONFLICT` with the batch in `details.batch`), and increments it, like the steps. Checks run in this order: not found, cancelled, locked, step 2 finished, version, values.

### 15.4 Endpoints

| Endpoint | Notes |
|---|---|
| `GET /production-plans` | `status`: `pending` (default; batch in progress), `confirmed` (batch in progress, step 3 not finished), `completed` (batch completed), `all` (any batch that isn't cancelled); `q` (batch code or supplier name); paging 20 (max 100). Newest production date first. Items: `batch_id`, `code`, `batch_status`, `supplier`, `production_date` (step 2), `quantity`, `wings_count`, `thighs_count`, `status`, `expected_big`, `expected_small`, `updated_at`. Also `pending_count` (plans waiting, whatever the filter). |
| `GET /production-plans/{batch_id}` | The plan (or `null` + `plan_legacy`), step 2 (`status`, `production_date`, wings / thighs kg and count, by-products with catalog names and kg, marinade g), step 3's actual packs and comment, the batch `version`, `status`, `current_step`, supplier and quantity, `sachets` (needed vs in stock, §15.3), and `editable` (step 2 finished, step 3 not finished, batch not cancelled). |
| `PATCH /production-plans/{batch_id}` | `production_plan.manage`. Body `{version, expected_big?, expected_small?, note?}` (partial; `null` clears). Returns the detail. |
| `POST /production-plans/{batch_id}/confirm` | `production_plan.manage`. Body `{version}`. Returns the detail. |

Audit: `production_plan.update` (field diff, only when something changed) and `production_plan.confirm` (§6).

---

## 16. Notifications

Production and order alerts, stored in the app (the bell) and sent on Telegram.

### 16.1 When and to whom

| Event | Type | Payload |
|---|---|---|
| Step 2 finished | `production.processing_finished` | `code`, `quantity`, `wings`, `thighs`, `actor_id`, `repeat` |
| Step 3 finished | `production.completed` | `code`, `matches`, `planned_big`, `planned_small`, `actual_big`, `actual_small`, `comment`, `actor_id`, `repeat` |
| Order out for delivery | `order.delivering` | `code`, `customer`, `customer_type`, `customer_phone`, `white`, `black`, `plastic_bag`, `delivery_bag` (box counts; alerts from before the bags have only `white` / `black`), `actor_id`, `repeat` |
| Order delivered, everything accepted | `order.delivered` | `code`, `customer`, `customer_type`, `customer_phone`, `actor_id`, `repeat` |
| Order delivered with returns | `order.return_pending` | `code`, `customer`, `customer_type`, `customer_phone`, `returned` (items), `reason`, `actor_id`, `repeat` |
| Preparation finished | `preparation.finished` | `code`, `type`, `sachets_2`, `sachets_4` (satay; null for a pack size not made), `materials` (packaging: `[{name_en, name_km, quantity, unit}]`), `actor_id`, `repeat` |
| Attendance request sent | `attendance.request_submitted` | `year`, `month`, `name`, `missing_minutes`, `salary_cut_minutes`, `unpaid_work_minutes`, `actor_id` (§22.15; to the reviewers in scope, not to every holder of the permission) |
| Attendance request approved | `attendance.request_approved` | `year`, `month`, `missing_minutes`, the **approved** `salary_cut_minutes` / `unpaid_work_minutes`, `with_changes`, `comment`, `actor_id` (to the employee) |
| Attendance request rejected | `attendance.request_rejected` | `year`, `month`, `missing_minutes`, the requested split, `reason`, `actor_id` (to the employee) |
| Request reminder (1st of the month) | `attendance.request_reminder` | `year`, `month` (the previous month), `missing_minutes`, `balance_minutes`, `deadline`, `deadline_day`, `deadline_month` (to the employee; `entity_type = user`) |
| Return reviewed | `order.returns_reviewed` | `code`, `customer`, `customer_type`, `customer_phone`, `outcome` (`partly_returned` / `fully_returned`), `to_stock`, `to_wasted` (items), `actor_id`, `repeat` |

- **Recipients:** every **active** user holding the alert's permission (effective permissions: granted, active permission, still assignable to the role), the superadmin implicitly. Production alerts: `production_plan.view` (the GM and the supervisors given plan access). Order alerts: `orders.review_returns` (the GM and the supervisors given Order returns). Preparation alerts: `preparation.update` (the GM and the supervisors given Preparation management). Staff hold none of them. The person who acted is included when they qualify. Order items in the payload are `[{item_code, name_en, name_km, count, kg}]` (names kept with the alert).
- `repeat` is `true` when the batch already had an alert of that type (e.g. step 2 finished again after a reopen); the text says "again".
- One `notifications` row per recipient is inserted **in the same transaction** as the Finish: an alert exists exactly when the step was finished.

### 16.2 Telegram delivery

**After the commit**, a background task sends one message per row, in the recipient's language (km/en), and records the outcome:

| `telegram_status` | Meaning |
|---|---|
| `pending` | not attempted yet |
| `sent` | delivered (`sent_at`) |
| `failed` | Telegram refused or couldn't be reached (blocked bot, network); `telegram_error` holds the reason and it's logged. **Not retried automatically.** |
| `not_linked` | the recipient has no Telegram account bound (they link it by pressing Start in the bot, §7.4; the next alert is then sent) |
| `bot_off` | no bot token, `BOT_MODE=off`, or webhook mode without a running bot |

- Webhook mode sends with the API's own bot; polling mode creates a short-lived bot in the API process (the poller is a separate process).
- **A Telegram problem never blocks or fails the Finish.**
- Retry failed ones manually: `python -m app.bot notifications resend-failed` (in Docker: `docker compose exec api python -m app.bot notifications resend-failed`).

**Messages** (HTML, user text escaped):

- ✅ *"{code}: processing finished — {quantity} chickens → {wings} wings, {thighs} thighs. Set the packaging plan."* Button **Open plan / បើកផែនការ**.
- 🎉 *"{code}: production completed as planned — {big} × 4-Piece Packs, {small} × 2-Piece Packs."* Button **Open batch / បើកផលិតកម្ម**.
- ⚠️ *"{code}: production completed, different from the plan. Planned {pb} / {ps}, actual {ab} / {as}. Comment: “{comment}”."* Button **Open batch**.

- 🚚 *"{code} for {customer} is out for delivery — {boxes}."* — `{boxes}` lists the containers that have boxes, e.g. *"2 white boxes, 1 plastic bag"* (*"ប្រអប់ស 2, ថង់ប្លាស្ទិក 1"*).
- ✅ *"{code}: delivered to {customer}, everything accepted."*
- ↩️ *"{code}: {customer} returned items — {3 × 4-Piece Packs, 0.250 kg Liver (packed)}. Reason: “{reason}”. Review the return."*
- 📦 *"{code}: return reviewed — partly / fully returned ({…} to stock, {…} wasted)."* (*nothing* when a side is empty)

- 🧂 *"{code}: preparation finished — 40 satay sachets (2-piece), 25 (4-piece) | Skewer 2.000 kg, String 0.500 kg."* (satay sachets, then each packaging material; "again" after a reopen). Button **Open preparation / បើកការរៀបចំ** → `/workstation/preparations/<id>`. Material names are escaped.

- 📝 *"{name} sent a request for October 2026: missing 6 h 45 — salary cut 2 h, unpaid work 4 h 45."* to the reviewers in scope: holders of `attendance.requests_review` whose scope includes the employee (§22.15), plus the superadmin. Button **Open request / បើកសំណើ** → `/attendance/requests?request=<id>`.
- ✅ *"Your request for October 2026 was approved: salary cut 2 h, unpaid work 4 h 45."* (with changes: *"… (with changes: “comment”)"*), ❌ *"Your request for October 2026 was rejected: “reason”."*, both to the employee, same button.
- 🔔 *"Your October 2026 balance is −6 h 45. Submit your request by 7 November."* on the 1st of the month, once per employee and month (§22.15). Button **Create request / ដាក់សំណើ** → `/attendance/requests`.

Order alerts have the button **Open order / បើកការបញ្ជាទិញ** → `/workstation/orders/<order id>`. The customer name, item names and the reason are escaped. `customer` is the order's snapshot (§19.2): the name, or `null` for a direct order, whose texts read *"Direct order · 012 345 678"* / *"ការបញ្ជាទិញផ្ទាល់ · 012 345 678"* (`customer_phone`, readable).

Buttons are inline `web_app` buttons to `MINI_APP_URL` + `/workstation/production-plans/<batch id>`, `/workstation/production/<batch id>?step=3` or `/workstation/orders/<order id>`; without an HTTPS `MINI_APP_URL` the message is text only. The texts never name who acted.

### 16.3 The bell

| Endpoint | Notes |
|---|---|
| `GET /notifications` | Own notifications, newest first; `unread_only`, paging (20, max 100). Each item: `id`, `type`, `entity_type`, `entity_id`, `payload` (without `actor_id`), `actor` (`UserRef`: "System" for the superadmin, §13), `created_at`, `read_at`, `telegram_status`. Also `unread_count` (all unread, whatever the page). |
| `POST /notifications/{id}/read` | Marks one read (idempotent). Someone else's → `404 NOTIFICATION_NOT_FOUND`. |
| `POST /notifications/read-all` | `{updated, unread_count}`. |

The UI marks an item whose `telegram_status` is `not_linked` or `failed` as not sent to Telegram.

---

## 17. Role limits

How many **active** general managers, supervisors and staff there may be. The superadmin is always exactly one and never listed.

### 17.1 Rules

| Role | Default | Allowed values |
|---|---|---|
| `general_manager` | 2 | 1–999 |
| `supervisor` | 3 | 1–999, or `null` = unlimited |
| `staff` | 10 | 1–999, or `null` = unlimited |

- Stored in `role_limits` (one row per role, seeded by migration `0008` and ensured on every start); out-of-range values → `VALIDATION_ERROR`.
- **Only active users count.** Deactivating someone frees their slot.
- **Checked when a user of that role becomes active:** creating a user (the target role), reactivating (the user's role) and changing role (the new role only, for an active user; the same role again is a no-op). A full role → `409 ROLE_LIMIT_REACHED` with `details = {role, limit, active}`. The message never names the superadmin.
- **Race-safe:** the check locks the role's `role_limits` row (`SELECT … FOR UPDATE`) and counts in the same transaction as the insert / update, so of several simultaneous requests for the last slot exactly one succeeds.
- **Lowering below the current count is allowed.** Nobody is deactivated; the role is simply full (`over_limit: true`) until enough users are deactivated or change role.
- **Existing data:** migration `0008` kept every active user, even where a role was already above its seeded limit.

### 17.2 Endpoints

| Endpoint | Notes |
|---|---|
| `GET /settings/role-limits` | Superadmin only (`FORBIDDEN_ROLE` for anyone else). `[{role, max_active, active, over_limit, updated_by (UserRef), updated_at}]` for the three roles. |
| `PUT /settings/role-limits/{role}` | Superadmin only. Body `{max_active: int \| null}`. Returns the same list. Setting the current value again writes nothing; a change writes `settings.role_limit_update` (`{role, from, to}`), hidden from general managers like everything the superadmin does. |
| `GET /users/role-capacity` | Anyone with `users.view` or `users.create`. `[{role, active, limit, full}]` for the roles the viewer manages only: superadmin all three, general manager supervisor and staff (never `general_manager`), supervisor staff. `limit: null` = unlimited; `full` = no new active user of that role now. |

`/auth/me` is unchanged.

---

## 18. Inventory

**Inventory (ស្តុក)** totals what production has made and used and what orders took, across all batches: a **ledger of movements** (`inventory_movements`, append-only) plus a **balance per item** (`inventory_balances`). Every production Finish writes movements; reopen and cancel write reversing movements; an order leaving for delivery takes its packs and packed by-products out, and its return review puts them back (stock or wasted). **Every production item changes only through production and orders**: nobody, not even the superadmin, changes it by hand. **Materials** (§18.11: string, skewers, sauces, bags…) are the exception: their stock is added and removed by hand, and step 2 uses the marinade. **Prepared items** (section **Prepared**, §18.12) change only through preparations (§21). **A balance can never go below zero.** The production process itself doesn't change: each batch still uses only its own chickens.

### 18.1 Items

Defined in `app/inventory/catalog.py`, in three **sections**: **stock**, **prepared** and **wasted**. Each item has a `code`, `name_en` / `name_km`, a display `group` (stock: `raw` / `processed` / `packed`; prepared: `prepared`; wasted: `wasted`), the units it tracks (`count`, `kg` or both) and an order.

| Section · group | Item (`code`) | Units | Comes from |
|---|---|---|---|
| stock · raw | Chicken / មាន់ (`chicken`) | count + kg | step 1 |
| stock · processed | Wings / ស្លាបមាន់ (`wings`), Thighs / ភ្លៅមាន់ (`thighs`) | count + kg | step 2 |
| stock · processed | By-product (processed), one per catalog by-product: e.g. Liver (processed) / ថ្លើមមាន់ (ផលិត) (`byproduct_processed.liver`) | kg | step 2 |
| stock · packed | 4-Piece Packs / កញ្ចប់ ៤ ដុំ (`packs_big`), 2-Piece Packs / កញ្ចប់ ២ ដុំ (`packs_small`) | count | step 3 |
| stock · packed | By-product (packed / carried forward), e.g. Liver (packed) / ថ្លើមមាន់ (វេចខ្ចប់) (`byproduct_packed.liver`) | kg | step 3 |
| prepared | Satay sachets (2-piece packs) / សាតេកញ្ចប់ (កញ្ចប់ ២ ដុំ) (`satay_sachet_2`), Satay sachets (4-piece packs) (`satay_sachet_4`) | count | satay sachet preparations (§21) |
| prepared | the **prepared twin** of each packaging material (`<material item_code>_prepared`, §18.12) | the material's unit | packaging preparations (§21) |
| wasted | Wings (`wasted.wings`), Thighs (`wasted.thighs`) | count + kg (**estimated**) | step 3 rejects |
| wasted | each by-product (`wasted.byproduct.liver`, …) | kg | step 3 rejected kg; packed by-products returned damaged (§19) |
| wasted | 4-Piece Packs (`wasted.packs_big`), 2-Piece Packs (`wasted.packs_small`) | count | packs returned damaged (§19) |

- The by-product items are generated from the production by-product catalog (§14.1), so a new by-product gets its three inventory items automatically; its balance rows are created at startup and on demand (no migration).
- Raw also lists the **materials** (§18.11), after Chicken; they are not in the catalog but in the `inventory_materials` table.
- A unit an item doesn't track is `null` everywhere (balance, movements, responses).
- **Units and precision, one rule everywhere** (`app/inventory/units.py`, mirrored by the UI's `lib/quantity.ts`): **count** = whole number; **kg** = 3 decimals (`"1.250"`); **g** = 1 decimal (`"350.0"`); **m²** (`m2`) = 2 decimals (`"12.50"`, 0.01 m², largest single entry 999,999,999.99). Production items use count and / or kg; a material uses exactly one of count, kg, g or m² (grams and square metres in their own `g` / `g_delta` / `balance_g_after` and `m2` / `m2_delta` / `balance_m2_after` columns, migration `0023`). m² converts to nothing: it isn't a weight and isn't a count.

### 18.2 Movements from production

Only for batches with `inventory_tracked = true` (§18.4). All quantities come from the batch's own finished values; units of 0 are skipped.

| Event | Movements |
|---|---|
| **Finish step 1** | Chicken +quantity, +weight_kg |
| **Finish step 2** | Chicken −quantity, −weight_kg · Wings +wings_count, +wings_kg · Thighs +thighs_count, +thighs_kg · each By-product (processed) +produced_kg · **Marinade sauce −marinade_g** (in the material's unit: g, or kg = g ÷ 1000 rounded to 3 decimals) |
| **Finish step 3** | Wings −wings_count, −wings_kg · Thighs −thighs_count, −thighs_kg · 4-Piece Packs +big_packages · 2-Piece Packs +small_packages · Wasted Wings +rejected_wings, +estimated kg · Wasted Thighs +rejected_thighs, +estimated kg · each By-product (processed) −(carry_kg + rejected_kg) · By-product (packed) +carry_kg · Wasted by-product +rejected_kg · **Satay sachets (4-piece) −sachets_4_used · Satay sachets (2-piece) −sachets_2_used**, split across preparations (below) |

- **Estimated waste kg** = rejected count × (step 2 kg ÷ step 2 count), rounded to 3 decimals, with `kg_estimated = true` on the movement (and `kg_estimated` on the wasted Wings / Thighs items).
- **By-products:** the processed stock loses only what step 3 assigned (carry + rejected). Since the by-product balance is a UI-only rule (§14.1), an unassigned remainder stays in the processed stock, visible; assigning more than the processed stock holds (all batches) is refused (§18.3).
- **Reopen** step N: the movements of every step sent back to draft are reversed, **latest step first**, each as a new movement with `reversal_of` = the original and `reason = "reopen"`. Finishing again writes fresh movements.
- **Cancel:** every un-reversed movement of the batch is reversed (`reason = "cancel"`). (A completed batch can't be cancelled, so that's at most steps 1 and 2.)
- A movement is reversed **at most once** (unique index on `reversal_of`). Draft saves never write movements.
- **Satay sachets consumed by production:** each size's count is taken from the preparations that made the sachets by their current net contribution, **oldest preparation first** (FIFO, the order of the item breakdown, §18.6): one movement per (item, preparation), `source = production`, with both `batch_id` (and `step = 3`) and `preparation_id`. So the sachet breakdown by preparation still adds up to the balance. A reversal keeps the original's `preparation_id`: reopening step 3 gives each preparation its sachets back. The batch's `stock_changes` sums them into one row per item.
- **Marinade reversal:** written in the material's **current** unit (it may have switched kg ↔ g since). Materials are left out of the "stock already used in orders" guard (§18.10): the marinade isn't attributed to batches.
- All in the same transaction as the action; the batch row is locked first, then the balances (§18.3).

### 18.3 No negative balances

Every change goes through one function (`inventory_service.apply_movements`):

1. lock the affected `inventory_balances` rows `FOR UPDATE`, **in `item_code` order** (a fixed order, so concurrent writers can't deadlock);
2. add up the deltas per item; if any balance would go below zero → `409 INVENTORY_INSUFFICIENT` with `details = {items: [{item_code, name_en, name_km, available_count, available_kg, available_g, needed_count, needed_kg, needed_g}]}` (needed = the net amount being removed, per unit; names included because whoever records production may not see the inventory). The **whole action** (Finish, reopen or cancel) is rolled back;
3. otherwise update the balances and insert the movements with `balance_count_after` / `balance_kg_after`.

So a Finish of step 2 needs the chickens and the marinade in stock, a reopen needs the later products still in stock (e.g. packs not yet gone), and a cancel needs the batch's processed products still there. Concurrent Finishes touching the same items take turns on the row locks and both succeed with correct totals.

### 18.4 Batches from before inventory

Migration `0010` added `production_batches.inventory_tracked`: **false for every existing batch**, true for batches created afterwards. Untracked batches never write movements (finish, reopen or cancel), so inventory starts at **zero** and stays consistent: reopening an old batch can't remove stock it never added. Their batch page says they aren't counted.

### 18.5 Production items are read-only

Each item has an **`origin`**: `production` (the catalog's production items: changes only through production — Finish, reopen, cancel — and orders — Delivering, return review), `manual` (the materials, §18.11) or `preparation` (the satay sachets and the prepared twins: changes only through preparations, §21).

- `POST /inventory/items/{item_code}/set` (guard `inventory.view`) answers `409 INVENTORY_ITEM_PRODUCTION_ONLY` (`details.item_code`) for **every** item, **for everyone, the superadmin included**: production items change only through production; materials through add / remove (`details.use = "material_add_remove"`). An unknown item → `404`. The body is validated first (`422`). The `inventory.adjust` permission stays inactive.
- **One-time reset (migration `0011`):** every `source = adjustment` movement was deleted; each remaining movement's `balance_count_after` / `balance_kg_after` was recomputed as a running total per item (by `created_at`, `id`), and `inventory_balances` set to the per-item totals. Inventory therefore reflects production only. The `inventory.adjust` audit entries stay as the record. Running it again changes nothing; it stops with an error instead of writing a negative balance (only possible if an adjustment had covered more by-product than the batches produced).

### 18.6 Where the stock came from (per batch)

`GET /inventory/items/{item_code}` (`inventory.view`, so everyone with Inventory) returns the item (`code`, names, `section`, `group`, units, `kg_estimated`, `origin`), its balance and `updated_at`, and **`sources`**: for each batch, the **net** quantity it currently contributes, the sum of all that batch's movements for the item, **every source** (production with its reversals, order stock-outs taken from it, returns given back to it), `[{batch_id, code, count, kg, kg_estimated, last_step}]`, only where the net isn't zero, **oldest batch first**. `last_step` is the latest of that batch's steps still contributing; `kg_estimated` is set when its contribution includes estimated kg. **The totals equal the balance.** No movement details (those need `inventory.history`). Untracked batches never appear.

**Prepared items** (origin `preparation`) answer `preparation_sources` instead: per preparation, the net quantity it currently adds (`[{preparation_id, code, prepared_date, count, kg, g}]`, oldest first, non-zero only; the totals equal the balance); `sources` is empty. Other items have `preparation_sources: []`.

Example: after two batches finish step 1 (100 + 50 chickens), Chicken lists both; once the 50-chicken batch finishes step 2 it drops out of Chicken and appears under Wings, Thighs and the processed by-products; after its step 3 it drops out of Wings and appears under the packs and wasted items.

The breakdown keeps adding up with orders because every order movement is **attributed to a batch** (§18.10): stock leaves oldest batch first, and returns go back to the batches it came from. A batch with only order movements for an item (e.g. wasted packs from a return) shows `last_step` 3.

### 18.7 History (`inventory.history`)

The movement history is behind **one** permission, `inventory.history` (feature **Inventory history**, GM and supervisor, Off · View only), **off by default**: only the superadmin sees it until it grants it.

- `GET /inventory/movements` needs it; so do the batch's `inventory_tracked` / `stock_changes` (`GET /production/{id}` and every response returning a batch leave both keys out without it).
- **Grantor must hold it** (`grantor_must_hold`, §12.3): the superadmin can set it on general managers and supervisors; a general manager can set it on supervisors **only while holding it**. For a general manager without it, the feature doesn't exist: it's left out of `GET /users/{id}/features`, `PUT /users/{id}/features/inventory_history` → `404 FEATURE_NOT_FOUND`, and its `feature.set` audit entries are hidden. It doesn't apply to staff, so supervisors never grant it. No cascade: taking it from a GM leaves the supervisors that GM granted.

### 18.8 Endpoints

| Endpoint | Guard | Notes |
|---|---|---|
| `GET /inventory` | `inventory.view` | `{sections: [{section, items: [{code, section, group, name_en, name_km, tracks_count, tracks_kg, tracks_g, tracks_m2, kg_estimated, origin, count, kg, g, m2, updated_at, material}]}]}`: stock, then prepared (the satay sachets, then the prepared twins by English name: every active packaging material's, and an archived material's only while it has stock; `material` = the twin's material, for its picture), then wasted. `updated_at` = the latest movement, `null` if it never changed. Every catalog item is listed (0 until it moves), and every **active material** in Raw right after Chicken (by English name; the UI sorts by the shown language) with `material = {id, unit, system_code, archived, icon_key, icon_url, prep_role}` (`null` for catalog items). |
| `GET /inventory/items/{item_code}` | `inventory.view` | §18.6. |
| `GET /inventory/movements` | `inventory.history` | Newest first. Filters: `item_code`, `section` (`stock` / `prepared` / `wasted`; materials count as stock, their twins as prepared), `source` (`production` / `adjustment` / `order` / `order_return` / `material_add` / `material_remove` / `material_unit_change` / `preparation`), `batch_id`, `batch_code` (part of the code), `order_id`, `preparation_id`, `date_from` / `date_to` (business days, `BUSINESS_TIMEZONE`); `page`, `page_size` (default 50, max 100). Each row: item and names, section, `count_delta`, `kg_delta`, `g_delta`, `m2_delta`, `kg_estimated`, `source`, `batch {id, code}` (for order movements: the batch the quantity is attributed to), `order {id, code}` (order movements, else `null`), `preparation {id, code}` (preparation movements, else `null`), `step`, `reversal_of`, `reason` (a material removal's reason; "reopen" / "cancel" on reversals), `balance_count_after`, `balance_kg_after`, `balance_g_after`, `balance_m2_after`, `created_by` (`UserRef`), `created_at`. History rows keep the unit they were written in (a kg ↔ g switch doesn't rewrite them). |
| `POST /inventory/items/{item_code}/set` | `inventory.view` | §18.5: `409 INVENTORY_ITEM_PRODUCTION_ONLY` for every item. |
| `/inventory/materials…` | see §18.11 | Materials: list, create, edit, archive, restore, add, remove; icon upload / delete / serve. |
| `GET /production/{id}` | `production.view` | With `inventory.history`: `inventory_tracked` and `stock_changes`, the batch's un-reversed movements `[{step, item_code, section, name_en, name_km, count_delta, kg_delta, g_delta, kg_estimated}]`, by step then item order (empty when untracked; step 2 includes the marinade). Without it both keys are absent. With `production.create`, while step 2 of a tracked, in-progress batch is a draft: `marinade_stock = {unit, count, kg, g}` (the Marinade sauce on hand, for the step 2 form); `null` otherwise. |

Weights are strings: kg with 3 decimals (`"4.200"`), g with 1 (`"350.0"`), like production.

### 18.9 Access

| Feature | Applies to | Levels |
|---|---|---|
| `inventory` (Inventory) | GM, supervisor, staff | Off · View only (`inventory.view`: stock, wasted, materials, per-batch breakdown) · Record (`+ inventory.materials_stock`: add / remove material stock) |
| `inventory_history` (Inventory history) | GM, supervisor (grantor must hold it) | Off · View only (`inventory.history`: movements, materials' too) |
| `inventory_materials` (Inventory materials) | GM, supervisor | Off · Full access (`inventory.materials_manage`: create, edit, archive, restore materials) |

- Defaults: general managers Inventory **Record** and Inventory materials **Full**; supervisors Inventory **Record** and Inventory materials **Off**; Inventory history **Off** for both; staff Off. The superadmin holds everything implicitly. The two material permissions were backfilled per these defaults when they were added.
- When `inventory.view` was added, the one-time backfill gave it to existing active general managers and supervisors; `inventory.history` is backfilled to nobody.
- A supervisor with Staff access can give staff Inventory View or Record, only up to its own level (§12.3).
- Redaction (§13): movements made by the superadmin (steps it finished) show "System" in `created_by`.

### 18.10 Orders and batches (FIFO)

Orders (§19) move only orderable items (the packs and the packed by-products). Every order movement carries **`order_id`** and the **`batch_id`** its quantity is attributed to, so the per-batch breakdown (§18.6) always equals the balance.

- **Delivering** (`source = order`, `inventory_service.take_for_order`): for each item, the order's total is taken from the batches by their **current net contribution, oldest batch first** (by creation time, then code), **one movement per (item, batch)**. Example: batches A (7 × 4-Piece) and B (7 × 4-Piece), an order of 10 → A −7, B −3; the breakdown then shows B 4. Not enough stock → `409 INVENTORY_INSUFFICIENT` (per item: available, needed) and nothing is written; the order stays Created.
- **Return review** (`source = order_return`, `return_from_order`): what goes **back to stock** returns to the batches the order took from, **newest first**, up to what each gave; what is **wasted** continues the same split into the item's wasted item (`wasted.packs_big` / `wasted.packs_small` / `wasted.byproduct.<code>`) **linked to the same batches**. Example (continued): 5 returned, 3 to stock and 2 wasted → B +3 (back to 7), 2 wasted 4-Piece Packs attributed to A.
- **Production guard** (`reverse`): a reopen (of step 3, or an earlier step that cascades to it) or a cancel takes back what the batch made; it needs the batch's **own** remaining contribution of each item to cover that. If part of it already left in orders → `409 PRODUCTION_STOCK_ALREADY_USED` (`details.items`: `remaining_*` / `needed_*` per unit and the order codes that took it; `details.orders`: all of them), nothing changes. Returned to stock, the packs count again (the reopen is then allowed); returned as wasted, they don't.
- **Locking:** the balance rows are locked (`FOR UPDATE`, `item_code` order) **before** the contributions are read, so a Delivering and a reversal on the same items take turns and each sees the other's movements. Lock order stays: the batch or order row, then the balances.

### 18.11 Materials

**Materials** are inventory items that don't come from production: string, skewers, stickers, sauces, bags… They appear in the **Raw** group after Chicken. Their stock is added and removed by hand; **Marinade sauce** is also taken by production step 2.

**Data** (`inventory_materials`, migration `0014`): `id`, `item_code` (`material_<8 hex>`, unique; the inventory item code used by balances and movements), `name_km`, `name_en` (both required, 1–100, whitespace collapsed), `unit` (`kg` | `g` | `m2` | `count`), `system_code` (unique, null; `marinade` for Marinade sauce), `icon_key` (null; a picture bundled with the UI, migration `0015`), `prep_role` (migration `0017`, §18.12), `icon` / `icon_mime` (an uploaded icon, both set or both null), `archived_at` / `archived_by`, `created_by` / `updated_by`, `created_at` / `updated_at`. Names are **unique among active materials, per language, case-insensitive** (partial unique indexes on `lower(name_km)` / `lower(name_en)` where not archived). Each material has one balance row in its unit and uses the same ledger (§18.3), `origin = manual`.

**Defaults** (seeded once at startup, then never re-created: an archived default stays archived), all at 0. The four stickers come in pairs: two counted in kg and two in m² (migration `0023` renamed the old two and added the m² ones, see below):

| `system_code` | km | en | unit | `icon_key` | `prep_role` |
|---|---|---|---|---|---|
| — | ខ្សែ | String | kg | `string` | `packaging` |
| — | ចង្កាក់ | Skewer | kg | `skewer` | `packaging` |
| — | ស្ទីកគ័រ (កញ្ចប់ ២ ដុំ) · គ.ក | Sticker (2-piece packs) · kg | kg | `sticker_2` | `packaging` |
| — | ស្ទីកគ័រ (កញ្ចប់ ៤ ដុំ) · គ.ក | Sticker (4-piece packs) · kg | kg | `sticker_4` | `packaging` |
| — | ស្ទីកគ័រ (កញ្ចប់ ២ ដុំ) · ម៉ែត្រការ៉េ | Sticker (2-piece packs) · m² | m2 | `sticker_2_m2` | `packaging` |
| — | ស្ទីកគ័រ (កញ្ចប់ ៤ ដុំ) · ម៉ែត្រការ៉េ | Sticker (4-piece packs) · m² | m2 | `sticker_4_m2` | `packaging` |
| `marinade` | ទឹកប្រឡាក់ | Marinade sauce | g | `marinade` | `none` |
| — | សាតេ | Satay sauce | g | `satay` | `satay_sauce` |
| — | ថង់ Zip 7 (កញ្ចប់ ២ ដុំ) | Zip bag 7 (2-piece packs) | kg | `zip_bag_2` | `zip_bag_2` |
| — | ថង់ Zip 7 (កញ្ចប់ ៤ ដុំ) | Zip bag 7 (4-piece packs) | kg | `zip_bag_4` | `zip_bag_4` |
| — | ថង់បឺតខ្យល់ | Vacuum bag | kg | `vacuum_bag` | `packaging` |

Marinade sauce is re-created on every start if it's missing (step 2 needs it). Migration `0015` backfilled `icon_key` on databases seeded before it (by English name; Marinade sauce by its system code). Materials created in the app have no `icon_key`.

**Migration `0023` (m², idempotent data step):** adds the `m2` columns and widens the CHECKs (`unit`, `has_delta`, preparation line `unit`). On a database whose defaults were already seeded (`app_settings.inventory_materials_seeded`) it **renames** the two kg stickers to the names above **only while they still have their seeded names** (both languages, unit kg; a sticker someone renamed is left alone) and **creates** the two m² stickers once (`prep_role = packaging`, balance 0, and a 0 balance for each prepared twin), skipping any whose `icon_key` or active name already exists. Every change writes a `material.update` / `material.create` audit entry with `details.source = "seed"` (no actor). On a fresh database the app seeds the same four stickers from `DEFAULTS`. Downgrade removes every m² material with its lines, movements and balances and restores the old names.

**Rules**

- **Add stock** (`inventory.materials_stock`): `quantity` > 0 in the material's unit and precision (count whole, kg ≤ 3 decimals, g ≤ 1 decimal, m² ≤ 2 decimals); otherwise `422 VALIDATION_ERROR` (`details.unit`). No note. Movement `source = material_add`.
- **Remove stock** (`inventory.materials_stock`): `quantity` as above and a **reason** (1–500 characters, trimmed). Never below zero → `409 INVENTORY_INSUFFICIENT`. Movement `source = material_remove`, `reason` kept.
- **Create / edit** (`inventory.materials_manage`): names and unit. Duplicate active name → `409 DUPLICATE_MATERIAL_NAME` (`details.fields`: `name_km` / `name_en`).
- **Unit change:**
  - **kg ↔ g: always allowed.** The balance is converted (× 1000 / ÷ 1000, rounded half-up to the new unit's precision) and one `material_unit_change` movement records the old unit out and the new unit in (e.g. `kg_delta −1.250`, `g_delta +1250.0`). Earlier history rows keep their own unit. The **prepared twin** (§18.12) is converted the same way (its own movement when it has stock).
  - **weight ↔ count, weight ↔ m², count ↔ m²: only while the material and its prepared twin have no movements at all** → otherwise `409 MATERIAL_UNIT_LOCKED` (square metres can't be converted to or from kg, g or a count). The empty balance just changes column; no movement is written.
- **Archive** (instead of delete): hides the material from Raw and the pickers; its balance and history stay. Archiving with stock is allowed (the UI warns). Adding or removing stock of an archived material → `409 MATERIAL_ARCHIVED`. **Restore** brings it back (its names must be free among active materials). Its archived name can be reused meanwhile.
- **System materials** (`system_code`, i.e. Marinade sauce): can be renamed and switched kg ↔ g; never archived or switched to count or m² → `409 MATERIAL_SYSTEM_LOCKED`.
- **Icon** (`inventory.materials_manage`): upload a **PNG, JPEG or WebP of at most 1 MB**, checked by decoding it (not by its name or declared type; at most 25 megapixels). It's rotated per its EXIF, **center-cropped to a square and resized to 256 × 256**, and stored as a PNG (transparency kept) in the row. A new upload replaces the old one; deleting it brings back `icon_key` / the unit icon. Not an image, another format, empty or over 1 MB → `422 VALIDATION_ERROR` (`details.fields[0].loc = ["body", "file"]`). The UI shows, in order: the uploaded icon, the `icon_key` picture, the unit icon.
- Every write locks the material row; step 2 reads Marinade sauce with a share lock, so a unit change and a step 2 Finish take turns.

**Marinade used by production:** see §14.1 and §18.2. The step 2 form shows what's on hand (`marinade_stock`, §18.8).

**Endpoints**

| Method | Path | Guard | Notes |
|---|---|---|---|
| GET | `/inventory/materials?include_archived=` | `inventory.view` | Active materials by English name; with `include_archived=true` the archived ones after them, **only for holders of `inventory.materials_manage`** (ignored for anyone else). Each: `id`, `item_code`, `name_km`, `name_en`, `unit`, `system_code`, `icon_key`, `prep_role`, `icon_url` (the uploaded icon, below; `null` without one), `count` / `kg` / `g` (the balance in its unit, others null), `has_movements`, `archived_at`, `archived_by`, `created_by`, `created_at`, `updated_by`, `updated_at` (`UserRef`s). |
| POST | `/inventory/materials` | `inventory.materials_manage` | `{name_km, name_en, unit}` → `201`. |
| PATCH | `/inventory/materials/{id}` | `inventory.materials_manage` | Partial `{name_km?, name_en?, unit?}`. |
| POST | `/inventory/materials/{id}/archive` · `/restore` | `inventory.materials_manage` | Idempotent. |
| POST | `/inventory/materials/{id}/add` | `inventory.materials_stock` | `{quantity}`. |
| POST | `/inventory/materials/{id}/remove` | `inventory.materials_stock` | `{quantity, reason}`. |
| GET | `/inventory/materials/{id}/icon` | `inventory.view` | The uploaded icon (`image/png`); `404 NOT_FOUND` without one. Clients use `icon_url`: `/inventory/materials/{id}/icon?v=<hash of updated_at>`, which changes with every upload, so the response is cacheable (`Cache-Control: private, max-age=31536000, immutable`). |
| PUT | `/inventory/materials/{id}/icon` | `inventory.materials_manage` | Multipart, field `file` (PNG / JPEG / WebP, ≤ 1 MB) → the material with its new `icon_url`. |
| DELETE | `/inventory/materials/{id}/icon` | `inventory.materials_manage` | Removes the upload (no-op without one) → the material. |

Unknown material → `404 MATERIAL_NOT_FOUND`. Every write returns the material. Audit (§6): `material.create`, `material.update` (`changes`, incl. `unit` and the converted `balance`; an icon change is `changes.icon = "changed"` / `"removed"`, never the image), `material.archive` (`balance`), `material.restore`, `material.stock_add` / `material.stock_remove` (`quantity`, `unit`, `balance_after`; `reason` on removals), `entity_type = material` (the audit log names it by its English name).

### 18.12 Prepared items

The **Prepared** section (`section = group = prepared`, shown as its own sub-tab between Packed and Wasted) holds what preparations (§21) make. Origin `preparation`: nobody sets or adds them by hand (`set` → `INVENTORY_ITEM_PRODUCTION_ONLY` like everything else; the material add / remove routes act on the raw material only).

- **Satay sachets:** `satay_sachet_2`, `satay_sachet_4` (count), catalog items. **Used by production step 3** (one per pack, §14.1), oldest preparation first (§18.2): their breakdown shows what each preparation still has. A preparation whose sachets production already used can't be reopened or cancelled: reversing needs **its own** remaining sachets → else `409 INVENTORY_INSUFFICIENT` with that remainder as `available_count` (§21).
- **Prepared twins:** every material with `prep_role = packaging` has a twin, `<material item_code>_prepared`, resolved from the material at runtime (no table): the **same names, unit and icon**, section Prepared. Its balance row is created at startup for existing materials and when such a material is created (and on demand). Archiving the material hides its twin from the overview **unless the twin has stock**. A kg ↔ g switch of the material converts the twin (§18.11); an m² material's twin is in m² too (2 decimals, `m2` column).
- **`prep_role`** (`inventory_materials`, migration `0017`): `none` (not preparable; Marinade sauce) · `packaging` (moved 1:1 to its twin; **the default for new materials**) · `satay_sauce` · `zip_bag_2` · `zip_bag_4` (the satay sachet inputs; at most one material each, a partial unique index). The migration set Marinade → none, Satay sauce / Zip bag 7 (2) / Zip bag 7 (4) by their icon key (else English name), everything else packaging. **It isn't editable in the UI yet (to be decided later)**; it's returned on materials (`prep_role`) and on the overview's `material`.
- History: preparation movements carry `source = preparation` and `preparation {id, code}`; the item detail lists preparations (§18.6).

---

## 19. Orders

**Orders (ការបញ្ជាទិញ)** under **Workstation**: what a customer receives, packed in **white or black boxes, plastic bags or delivery bags**, its delivery and what comes back.

```
created ──► delivering ──► success                 (customer accepted everything)
   │        (stock out)    return_pending ──► partly_returned / fully_returned
   └──► cancelled (customer cancelled; only while created)
```

No step back: a delivering order never returns to Created.

### 19.1 Data

| Table | Columns |
|---|---|
| `orders` | `id`, `code` (unique, `OR-YYYYMMDD-NNN`), `customer_type` (`saved` \| `direct`), `customer_id` (FK, RESTRICT; null for direct orders), `customer_name` / `customer_phone` (normalized) / `customer_location` (the customer snapshot, §19.2; migration `0016`), `delivery_date` (default today), `driver_id` (FK users, null), `note` (≤ 1000), `status`, `return_reason`, `cancel_reason` (≤ 500), `version`, `print_count` (delivery notes generated, §19.6; not part of `version`), `created_by` / `updated_by` / `delivering_by` / `delivered_by` / `returns_reviewed_by` / `cancelled_by`, `created_at`, `updated_at`, `delivering_at`, `delivered_at`, `returns_reviewed_at`, `cancelled_at` |
| `order_boxes` | `id`, `order_id` (cascade), `color` (the container: `white` \| `black` (boxes), `plastic_bag` \| `delivery_bag` (bags, migration `0026`); a code: it can carry meaning later), `position` (1, 2, … unique per order), `returnable` (the container must come back, §19.7), `container_status` (`pending` \| `returned` \| `not_returned`; null when not returnable or the order was cancelled), `container_reason` (≤ 300, required for `not_returned`), `container_recorded_by` / `_at`, `container_returned_later_by` / `_at` (migration `0028`) |
| `order_box_items` | `id`, `box_id` (cascade), `item_code`, `count` (packs, whole > 0) **xor** `kg` (packed by-products, > 0, 3 decimals), `position`; one line per item per box. **Lines are rows** so `unit_price` / `amount` can be added later without restructuring. |
| `order_return_items` | `id`, `order_id`, `item_code` (unique per order), `returned_count` / `returned_kg`, `to_stock_count` / `to_stock_kg`, `to_wasted_count` / `to_wasted_kg` (null until reviewed), `reviewed_by`, `reviewed_at` |
| `order_counters` | `day`, `last_number` (codes per creation day, like production) |

CHECKs: the statuses, the customer types (`saved` ⇒ `customer_id`; `direct` ⇒ no `customer_id` and a `customer_phone`), the colours, `count` xor `kg` > 0 on lines and returns, the split ≥ 0 and (once reviewed) stock + wasted = returned. **Orderable items:** `packs_big` (4-Piece Packs), `packs_small` (2-Piece Packs) and every `byproduct_packed.<code>` (the same codes as inventory, §18.1).

### 19.2 Rules

- **Customer.** Either a **saved customer** (`{customer_type: "saved", customer_id}`; `customer_type` defaults to `saved`) or a **direct order** (ការបញ្ជាទិញផ្ទាល់, `{customer_type: "direct", phone, location?}`): no saved customer and no name, a **phone (required)** and a **location (optional)** for this order only; nothing is added to Customers.
  - Saved: the customer must exist and be **active** (`CUSTOMER_NOT_FOUND` / `CUSTOMER_INACTIVE`, 422; an edit may keep an order's current customer after they were deactivated). `phone` / `location` aren't accepted (`VALIDATION_ERROR`); the order copies the customer's name, phone and location (no per-order override).
  - Direct: no `customer_id` (`VALIDATION_ERROR`); `phone` missing or empty → `VALIDATION_ERROR` (`details.fields[0].loc = ["body", "phone"]`), otherwise normalized like customers' phones (§11, 8–15 digits, optional `+`; `INVALID_PHONE`); `location` trimmed, ≤ 255, empty → null.
  - **Snapshot.** The order stores `customer_name` / `customer_phone` / `customer_location` and shows only those (responses, list, search, alerts, the delivery note, audit). They're **refreshed on every create and edit while the order is Created** (an edit that doesn't touch the customer re-copies the saved customer's current details) and **once more when delivery starts**; **from Delivering on they're frozen**, so later edits of the customer never change the order.
- **Create** (`orders.create`): the customer (above); the driver, optional, an **active staff member or supervisor** (`DRIVER_NOT_ALLOWED`); ≥ 1 box, each with ≥ 1 line; only orderable items, in their unit, one line per item per box (`VALIDATION_ERROR`, with `details.fields` locations such as `["body", "boxes", "1", "lines", "0", "count"]`). Stock is **not** touched: the response's `stock_warnings` lists items whose current stock is below the order's totals.
- **Edit** (`orders.update`, Created only): partial; `boxes` replaces every box and line; the driver is checked only when it changes. The customer is **replaced as a whole** when `customer_type` or `customer_id` is sent (same rules as create; switching between saved and direct is allowed); `phone` / `location` alone edit a direct order (the other one is kept; on a saved order → `VALIDATION_ERROR`). Audit diff (§6), including customer type, name, phone and location.
- **Cancel** (`orders.cancel`, Created only): reason required (the UI pre-fills "Customer cancelled").
- **Delivering** (`orders.create`, from Created): the order's totals leave stock, oldest batch first (§18.10); not enough → `INVENTORY_INSUFFICIENT` and it stays Created.
- **Delivered** (`orders.create`, from Delivering): `outcome: accepted` → **success** (no items allowed); `outcome: returned` with a **reason** and items, each > 0 and ≤ what was delivered of that item, listed once → **return_pending**. Either outcome also records the **containers** (§19.7).
- **Review returns** (`orders.review_returns`, from Return pending): every returned item exactly once, back to stock + wasted = returned (in its unit) → **fully_returned** when everything delivered came back, otherwise **partly_returned**. Stock goes back to its batches; wasted goes to the wasted items (§18.10).
- **Concurrency:** every write locks the order row and uses the order **`version`**; checks run: not found → status (`ORDER_INVALID_STATUS`, `details.status`) → version (`409 ORDER_CONFLICT`, current order in `details.order`) → values; `version` + 1.
- Packs are whole numbers everywhere; by-products kg with 3 decimals (strings in responses).

### 19.3 Endpoints

| Endpoint | Guard | Notes |
|---|---|---|
| `GET /orders` | `orders.view` | Filters `status` (`all`, a status, or `completed` = success + partly + fully returned), `customer_type` (`saved` / `direct`), `customer_id` (one saved customer), `driver_id`, `date_from` / `date_to` (delivery date), `q` (the code, the order's customer name or location, or phone digits: `012 345` finds `012345678`); newest delivery date first; paging 20 (max 100). Items: `code`, `status`, `customer` (below), **`customer`** (here and on the order): `{type: saved | direct, id (null for direct), name (null for direct), phone (normalized), phone_display, location, is_active (the saved customer's current status; null for direct)}`, from the snapshot. Stats aren't affected. `delivery_date`, `driver` (`UserRef`), `white_boxes`, `black_boxes`, `plastic_bag_boxes`, `delivery_bag_boxes`, `containers_outstanding` (boxes not returned), `created_at`, `updated_at`. Filter `containers=outstanding`: orders with at least one box recorded as not returned (§19.7). |
| `GET /orders/stats` | `orders.view` | `created`, `delivering`, `return_pending` (now) and `delivered_this_month` (delivered in the current month, `BUSINESS_TIMEZONE`). |
| `GET /orders/{id}` | `orders.view` | The order, its timestamps and who did each step, `boxes` with `lines` (`item_code`, names, `unit`, `count` / `kg`) and the container fields (`returnable`, `container_status`, `container_reason`, `container_recorded_by` / `_at`, `container_returned_later_by` / `_at`), **`containers`** (`{total_returnable, returned, not_returned, pending}`; null for cancelled orders), **`summary`** (per colour: `boxes` and the items' totals; `total`: all boxes), `returns` (delivered / returned / to stock / to wasted per item, reviewer), `stock_warnings` (only while Created). |
| `GET /orders/customer-options` | `orders.create` or `orders.update` | Active customers `{id, name, phone_display, location}` (`q` on name or phone digits; at most 20), **no Customers access needed**. |
| `GET /orders/driver-options` | `orders.create` or `orders.update` | Active staff and supervisors `{id, full_name, role}`. |
| `GET /orders/available-stock` | `orders.create` or `orders.update` | The orderable items with their current balance (`unit`, `count` / `kg`). |
| `POST /orders` | `orders.create` | `{customer_type?: saved, customer_id}` or `{customer_type: direct, phone, location?}`, plus `{delivery_date?, driver_id?, note?, boxes: [{color, returnable?, lines: [{item_code, count? \| kg?}]}]}` → `201`. |
| `PATCH /orders/{id}` | `orders.update` | `{version, …same fields, all optional}` (customer rules in §19.2). |
| `POST /orders/{id}/cancel` | `orders.cancel` | `{version, reason}`. |
| `POST /orders/{id}/delivering` | `orders.create` | `{version}`. |
| `POST /orders/{id}/delivered` | `orders.create` | `{version, outcome: accepted}` or `{version, outcome: returned, reason, items: [{item_code, count? \| kg?}]}`, both with `containers: [{box_id, returned, reason?}]` (every returnable box once, §19.7). |
| `POST /orders/{id}/boxes/{box_id}/container-returned` | `orders.containers` | No body. A box recorded as not returned → returned (§19.7). |
| `POST /orders/{id}/returns/review` | `orders.review_returns` | `{version, items: [{item_code, to_stock_count?, to_stock_kg?, to_wasted_count?, to_wasted_kg?}]}`. |
| `GET /orders/{id}/document.pdf` | `orders.view` | The delivery note (§19.6), `application/pdf`, `inline; filename="<code>.pdf"`, `Cache-Control: no-store`. |
| `GET /orders/delivery-note/supplier` | `orders.export_delivery_note` | `{name_km, name_en, address_km, address_en, phone, phone_display}` from Business info. The Excel itself is built and downloaded in the browser from `public/templates/delivery_note_template.xlsx`: nothing is generated or stored by the API. |
| `POST /orders/{id}/document/send-telegram` | `orders.view` | The bot sends the delivery note to the requester's own chat → `{copy_number}` (§19.6). |

Delivering, Delivered and the review store their alerts in the same transaction and send them to Telegram after the response (§16).

### 19.4 Access

| Feature | Applies to | Levels |
|---|---|---|
| `orders` (Orders) | GM, supervisor, staff | Off · View only (`orders.view`) · Record (`+ orders.create`) |
| `order_management` (Order management) | GM, supervisor | Off · Full access (`orders.update`, `orders.cancel`) |
| `order_returns` (Order returns) | GM, supervisor | Off · Full access (`orders.review_returns`; receives the order alerts) |
| `order_export` (Export delivery note) | GM, supervisor, staff | Off · Full access (`orders.export_delivery_note`). The GM has it by default; supervisors and staff only when granted. A supervisor can give it only to their own staff and only while holding it (`PERMISSION_NOT_HELD` otherwise) |
| `order_containers` (Order containers) | GM, supervisor, staff | Off · Full access (`orders.containers`: mark boxes returned later, §19.7). GM Full by default; supervisors and staff Off. Same supervisor cap as above |

Defaults: general managers Orders **Record**, management and returns **Full**; supervisors Orders **Record**, management and returns **Off**; staff Off; the superadmin implicitly everything. Backfilled to existing users per these defaults (§5.3). A supervisor with Staff access sets staff Orders up to its own level (§12.3).

### 19.5 Prices later

Orders have no prices yet. Because each line is its own row (`order_box_items`), adding `unit_price` / `amount` columns (and a total on the order) won't restructure anything; the box colour is stored as a code so a colour can later carry a price list. The delivery note is already built for it (§19.6): the same document becomes the invoice.

### 19.6 Delivery note (ប័ណ្ណដឹកជញ្ជូន)

Every order can be printed as a **delivery note** on an **80 mm receipt printer**, from **Created** onward (any status, Cancelled included), by anyone with `orders.view`. The API renders the PDF (server-side, so it works the same from a PC browser and from the Telegram Mini App, where printing isn't reliable).

**Page.** 80 mm wide, 3 mm margins (printable ~72 mm), **as tall as the content** (no wasted paper; at least 60 mm). **Black and white only**, for thermal printers: no colours or greys carry meaning; the container is text plus a marker (■ filled square = ប្រអប់ខ្មៅ / Black box, □ outlined square = ប្រអប់ស / White box, dashed outline = ថង់ប្លាស្ទិក / Plastic bag, ◩ half filled = កាបូបដឹកជញ្ជូន / Delivery bag). Base font 9 pt **Kantumruy Pro** (bundled with the API, so Khmer is shaped correctly everywhere); every label in Khmer with the English in smaller text under it; numbers right-aligned; thin rules between sections.

**Content**, top to bottom:

1. Logo (if set), business name (km, en), address (km, en), phone: the business info (§20).
2. **ប័ណ្ណដឹកជញ្ជូន / DELIVERY NOTE** (every print looks the same: no original / COPY mark); a **បានលុបចោល / CANCELLED** banner on cancelled orders (with the cancel reason); order code, printed date-time (`BUSINESS_TIMEZONE`, dd/mm/yyyy HH:MM), status.
3. Customer (name, phone, location; a direct order reads **ការបញ្ជាទិញផ្ទាល់ / Direct order** with its phone and location), from the order's snapshot (§19.2), delivery date. (No driver on the note.)
4. **White boxes**, **Black boxes**, **Plastic bags**, then **Delivery bags** (containers without boxes left out): each box ("ប្រអប់ទី 1 / Box 1", numbered like the order page) with its lines (short item name km + en: "កញ្ចប់ ៤ ដុំ / 4-Piece Packs", "ថ្លើមមាន់ / Liver"; packs as a count, by-products as kg with 3 decimals). No subtotals and no grand total.
5. **Returned**, only when the order has returns: returned quantity per item, after the review also back to stock / wasted, and the reason.
6. Note.
7. **ប្រអប់ត្រូវយកមកវិញ / Containers to return**, only when the order has returnable boxes (not on cancelled orders): per returnable box an empty square to tick by hand, "ប្រអប់ទី 1 · ប្រអប់ស / Box 1 · White box", a "បានយកមកវិញ / Returned" line and "មូលហេតុ / Reason:" with a blank line to write on. Same fonts and spacing; the page height still fits the content. (The Excel export doesn't have it.)
8. **រៀបចំដោយ / Prepared by** with the order's creator's name (no signature or date line), then **អ្នកទទួល / Received by** with a signature line and **កាលបរិច្ឆេទ / Date: 26/10/2026**, the order's delivery date filled in (dd/mm/yyyy).
9. The footer note (km, en), when set in Business info. (No QR code.)

An invoice (prices on, later) adds one **Total amount** line after the boxes; the delivery note has no totals.

User names follow redaction (§13): an order the superadmin created reads "Prepared by: System".

**Counted, not marked.** Each generated note (download or Telegram) increments `orders.print_count`; the document itself carries no original / COPY mark (removed: the app shows how many times it was exported). Two prints at the same moment get distinct numbers (the increment locks the order row). Printing doesn't change the order's `version` (nobody gets `ORDER_CONFLICT` because someone printed). Each one writes `order.document_printed` (`copy`: the print number, `via`: `download` / `telegram`). If rendering or sending fails, nothing is counted or audited.

**Send to my Telegram.** `POST /orders/{id}/document/send-telegram`: the bot sends the PDF (`<code>.pdf`) to the requester's **own** linked chat as a document, captioned "🧾 Delivery note **<code>** · <customer>" in their language (escaped; a direct order: "Direct order · <phone>"). Checks: bot off (no token, `BOT_MODE=off`, webhook mode without a runtime) → `503 TELEGRAM_NOT_CONFIGURED`; then no linked Telegram account → `409 TELEGRAM_NOT_LINKED` (staff, supervisors and GMs are linked on their first Mini App sign-in; the superadmin links in its profile, §7.5); Telegram refuses or can't be reached → `502 TELEGRAM_SEND_FAILED`. Same bot as the alerts (§16.2): the API's own in webhook mode, a short-lived one in polling mode.

**Rendering.** HTML template (Jinja2) → PDF (WeasyPrint), in a worker thread (at most 2 at once) with a 20 s timeout; WeasyPrint's system libraries missing (e.g. a plain Windows machine) or too slow → `503 DOCUMENT_UNAVAILABLE`. Details in ARCHITECTURE §5 "Documents (delivery notes)".

**Prices later.** The template already has `unit_price` / `amount` columns and a money total behind a `show_prices` flag (off today). One function (`documents/delivery_note.py: kind_for`) decides the document kind: when orders have prices it returns the invoice kind and the same template prints **វិក្កយបត្រ / INVOICE** with the money columns.

### 19.7 Returnable containers

White and black boxes usually come back from the customer; bags don't. Each box says whether its container must come back (`returnable`) and what happened to it.

- **Defaults per type** (`BOX_RETURNABLE` in `models/order.py`, next to `BOX_COLORS`; every container type must declare one, checked at import): white box, black box → returnable; plastic bag, delivery bag → not.
- **Create / edit** (while Created): each box takes `returnable` (bool); omitted → the type's default. An edit replaces every box, so a box whose type changed without `returnable` gets the new type's default. Returnable boxes start `pending`.
- **Delivered** (both outcomes): `containers: [{box_id, returned, reason?}]` must list **every returnable box exactly once**; missing, extra (not returnable, unknown) or repeated boxes → `422 ORDER_CONTAINERS_REQUIRED` (`details.box_ids`: missing; `details.extra_box_ids`). `returned: false` needs a reason (≤ 300; blank → `VALIDATION_ERROR` at `["body", "containers", n, "reason"]`); a reason sent with `returned: true` is ignored. Sets `container_status` (`returned` / `not_returned`), the reason and `container_recorded_by` / `_at`; audited as `order.containers_recorded`. An order without returnable boxes sends `containers: []` (or nothing).
- **Returned later** (`POST /orders/{id}/boxes/{box_id}/container-returned`, `orders.containers`): only a box recorded as `not_returned` (so only on a delivered order, any final status) → `returned`, keeping the original reason, with `container_returned_later_by` / `_at`; anything else → `409 ORDER_CONTAINER_STATE`; a box of another order → `404 ORDER_NOT_FOUND`. It locks the order row but, like printing, **doesn't change `version`** (nobody reviewing the returns gets `ORDER_CONFLICT` because a box came back). Audited as `order.container_returned`.
- **Cancelled orders:** cancelling clears every `container_status` (nothing left, nothing to bring back); `containers` is null and the delivery note has no Containers section.
- **Responses:** per box the fields above (user refs as `UserRef`, redacted, §13); the order's `containers` summary `{total_returnable, returned, not_returned, pending}`; list items `containers_outstanding` and the list filter `containers=outstanding`.
- **Existing orders** (migration `0028`): boxes of Created / Delivering orders got the type defaults (and `pending`); boxes of finished or cancelled orders `returnable = false` (no history to invent).

---

## 20. Business info

**Settings → Business info (ព័ត៌មានអាជីវកម្ម):** what delivery notes (§19.6) print at the top and bottom.

### 20.1 Data

One row, `business_settings` (`id = 1`, CHECK), migration `0013`:

| Column | Notes |
|---|---|
| `name_km`, `name_en` | Required, ≤ 200; whitespace collapsed. Seeded with "មាន់អាំងមានជ័យ" / "Mean Chey Grilled Chicken". |
| `address_km`, `address_en` | Optional, ≤ 500; line breaks kept (printed as lines). |
| `phone` | Optional; normalized with `core/phones.py` (`INVALID_PHONE`), shown as `phone_display`. |
| `footer_note_km`, `footer_note_en` | Optional, ≤ 300 (e.g. "សូមអរគុណ!" / "Thank you!"). |
| `logo`, `logo_mime` | Optional PNG or JPEG (bytea), both set or both null (CHECK). |
| `updated_by`, `updated_at` | |

Empty strings mean "not set". If the row is ever missing (e.g. a truncated test database), it's recreated with the default names on first read.

### 20.2 Rules

- **Text** (`PUT /settings/business`): replaces every text field (names required; send the optional ones as `null` or `""` to clear them). Unknown fields → `VALIDATION_ERROR`.
- **Logo** (`PUT /settings/business/logo`, multipart `file`): checked by decoding it, not by its name or declared type. Not a PNG / JPEG, empty, over **500 kB**, or a bitmap over 25 megapixels → `422 VALIDATION_ERROR` (`loc = ["body", "file"]`). Stored **resized to at most 400 px wide** (same format, proportions kept); smaller images are stored as uploaded. `DELETE` removes it.
- **Audit:** `settings.business_update` with the changed fields (`[old, new]`), the logo as `"changed"` / `"removed"`; nothing written when nothing changed.
- **Preview** (`GET /settings/business/preview.pdf`): a delivery note with the current business info, marked **គំរូ / SAMPLE**: the latest order when the requester holds `orders.view`, otherwise made-up data (so Business info alone doesn't show order data). Not counted, not audited.

### 20.3 Endpoints and access

| Endpoint | Notes |
|---|---|
| `GET /settings/business` | `name_km`, `name_en`, `address_km`, `address_en`, `phone`, `phone_display`, `footer_note_km`, `footer_note_en`, `has_logo`, `logo_mime`, `updated_by` (`UserRef`), `updated_at`. |
| `PUT /settings/business` | The text fields → the same. |
| `GET /settings/business/logo` | The image (`image/png` / `image/jpeg`); `404 NOT_FOUND` without a logo. |
| `PUT /settings/business/logo` | Multipart upload → the same as `GET /settings/business`. |
| `DELETE /settings/business/logo` | → the same. |
| `GET /settings/business/preview.pdf` | The sample delivery note (PDF). |

All guarded by `settings.business_info`: the superadmin implicitly; a **general manager** only when the superadmin sets its **Business info** feature to Full access (§12.1; default Off, not backfilled). Supervisors and staff can't hold it.

---

## 21. Preparation

**Workstation → Preparation (ការរៀបចំ):** raw materials made **ready to use**. **Not to be confused with production step 3 (Standardize / packaging)**: a preparation only converts materials into prepared materials.

```
New preparation (type) → PP-YYYYMMDD-NNN, draft (autosave)
  Finish  → stock moves (inputs out, outputs in), prepared date recorded, managers alerted
  Reopen  → back to draft, values kept, movements reversed, date cleared       (preparation.update)
  Cancel  → draft: cancelled; finished: movements reversed, then cancelled      (preparation.cancel)
```

### 21.1 Types and lines

| Type | Lines | Inputs (entered) | Output (entered) |
|---|---|---|---|
| `satay_sachet` — ធ្វើសាតេកញ្ចប់ / Make satay sachets | one per pack size (2 and / or 4) | Satay sauce used (`satay_g`, g, 1 decimal), Zip bag 7 of that pack size used (`zip_bag_qty`, in that material's unit) | Satay sachets of that pack size (`sachets`, count) |
| `packaging_material` — រៀបចំសម្ភារៈវេចខ្ចប់ / Prepare packaging materials | one per material (`prep_role = packaging`) | `quantity` of the material (its unit) | the **same quantity** of its prepared twin (**1:1**, same unit) |

All values are typed in (**no recipe yet**). Lines are stored with `unit` (the material's unit when saved): a later kg ↔ g switch is converted at Finish; a switch to / from count or m² needs the line re-entered (`VALIDATION_ERROR`). A packaging line of an m² material moves the same quantity (2 decimals) to its twin; `INVENTORY_INSUFFICIENT` then reports `available_m2` / `needed_m2`.

### 21.2 Data (migration `0017`)

- `preparations`: `id`, `code` (unique, `PP-YYYYMMDD-NNN`: the creation day in `BUSINESS_TIMEZONE`, numbered per day by `preparation_counters`, so concurrent creations get distinct numbers), `type`, `status` (`draft` | `finished` | `cancelled`), `prepared_date` (recorded at Finish, cleared on reopen; CHECK finished ⇔ date), `note` (≤ 1000), `cancel_reason` (≤ 500), `version`, `created_by` / `updated_by` / `finished_by` / `cancelled_by` and their times.
- `preparation_lines`: `id`, `preparation_id` (FK, cascade), `position`, satay fields (`pack_size` 2 | 4, `satay_g`, `quantity` = zip bags, `sachets`) or packaging fields (`material_id` FK RESTRICT, `quantity`), `unit`; CHECKs: one kind per line, values ≥ 0; unique (`preparation_id`, `pack_size`) and (`preparation_id`, `material_id`).
- `inventory_movements.preparation_id` (FK, SET NULL) with `source = preparation`.

### 21.3 Rules

- **Drafts** (`PATCH`, `preparation.create`): `{version, lines?, note?}`; `lines` replaces every line. Partial values are fine; only types, ≥ 0, the unit's precision and the line kind are checked (satay fields on a packaging preparation or the other way round, a missing `pack_size` / `material_id`, a duplicate, an unknown material or one whose `prep_role` isn't `packaging` → `VALIDATION_ERROR`). Every write (draft, finish, reopen, cancel) locks the row and needs the current `version` (stale → `409 PREPARATION_CONFLICT` with the current preparation); checks run: not found → cancelled (`PREPARATION_CANCELLED`) → status (`PREPARATION_INVALID_STATUS`) → version → values.
- **Finish** (`preparation.create`): ≥ 1 line; every value present and **> 0**; the materials **active** (`MATERIAL_ARCHIVED`) and with the right `prep_role` (`VALIDATION_ERROR`); then in one transaction (the materials read with a share lock, so a unit change waits):
  - satay line: −satay sauce (the grams, converted when the material is in kg), −zip bag 7 (2 or 4), +satay sachets (2 or 4);
  - packaging line: −material, +its prepared twin (same quantity and unit, also for g and counted materials);
  - **not enough stock → `409 INVENTORY_INSUFFICIENT`** (items, available, needed; §18.3) and nothing changes;
  - `prepared_date` = today in `BUSINESS_TIMEZONE`; movements `source = preparation`, `preparation_id`; the alert is stored (§16).
- **Reopen** (`preparation.update`): finished → draft, values kept; its open movements are reversed (`reversal_of`, `reason = "reopen"`, in each item's current unit); blocked by `INVENTORY_INSUFFICIENT` when the outputs are no longer in stock, or when production step 3 already used this preparation's sachets (its **own** remaining count must cover them, §18.12); `prepared_date` cleared.
- **Cancel** (`preparation.cancel`, reason 1–500 required): a draft is cancelled; a finished one is reversed first (`reason = "cancel"`, same block). Cancelled is read-only.
- **Audit** (`entity_type = preparation`): `preparation.create`, `preparation.finish`, `preparation.reopen`, `preparation.cancel` (§6). Draft saves aren't audited.

### 21.4 Endpoints

| Endpoint | Guard | Notes |
|---|---|---|
| `GET /preparations` | `preparation.view` | Filters `type`, `status` (`all` = draft + finished, `draft`, `finished`, `cancelled`), `include_cancelled`, `date_from` / `date_to` (the prepared date, or the creation day while not finished), `q` (the code, or a material name in km / en: a packaging line's material, or the satay inputs for satay preparations); newest first; paging 20 (max 100). Items: `id`, `code`, `type`, `status`, `prepared_date`, `created_at`, `outputs` (below), `created_by`. |
| `GET /preparations/stats` | `preparation.view` | `drafts` (now), `finished_this_month`, `sachets_2_this_month`, `sachets_4_this_month` (finished, prepared date in the current month, `BUSINESS_TIMEZONE`). |
| `GET /preparations/material-options` | `preparation.create` | Active packaging materials by English name with `stock` and `prepared_stock` (no Inventory access needed). |
| `POST /preparations` | `preparation.create` | `{type}` → `201`, a draft. |
| `GET /preparations/{id}` | `preparation.view` | The preparation: `lines` (satay: `pack_size`, `satay_g`, `zip_bag_qty`, `sachets`; packaging: `material` with its current `stock` / `prepared_stock`, `quantity`; both `unit`), `satay_materials` (satay only: the `satay_sauce`, `zip_bag_2`, `zip_bag_4` materials with their stock, null when missing), `inputs` / `outputs` (what the lines take and make, from values > 0: `{item_code, name_en, name_km, unit, quantity, material_id, icon_key}`), the user references and times. Quantities are strings in the unit's precision (`"12"`, `"1.250"`, `"350.0"`). |
| `PATCH /preparations/{id}` | `preparation.create` | Draft save. |
| `POST /preparations/{id}/finish` | `preparation.create` | `{version}`. |
| `POST /preparations/{id}/reopen` | `preparation.update` | `{version}`. |
| `POST /preparations/{id}/cancel` | `preparation.cancel` | `{version, reason}`. |

User references are `UserRef`s (redacted, §13); the routes are part of the redaction and superset sweeps.

### 21.5 Access and alerts

| Feature | Applies to | Levels |
|---|---|---|
| `preparation` (Preparation) | GM, supervisor, staff | Off · View only (`preparation.view`) · Record (`+ preparation.create`) |
| `preparation_management` (Preparation management) | GM, supervisor | Off · Full access (`preparation.update`, `preparation.cancel`; **receives the preparation alerts**) |

Defaults: general managers Record + Full; supervisors Record + Off; staff Off; the superadmin implicitly everything; backfilled per these defaults (§5.3). A supervisor with Staff access gives staff Preparation up to its own level (§12.3).

**Alerts:** finishing a preparation notifies every active holder of `preparation.update` (bell + Telegram when linked), stored in the Finish transaction and sent after the commit like production and order alerts (§16); a re-finish after a reopen says "again".

---

## 22. Attendance

**Attendance (វត្តមាន)**, its own top-level section: tracked employees check in and out from the **Telegram Mini App** with the phone's GPS; the server decides the time, the shift and the one next action; a scheduler marks absences and forgotten check-outs and sends reminders; early check-ins and overtime count as extra time; each employee (and their managers) sees a month or a year of KPIs and days; managers see each day and fix records with a reason; **Scheduling** (§22.14) sets the tracked weekdays, holidays and each workplace's shift times and rules from a chosen date.

```
06:30  reminder "Morning check-in is open until 07:44"  →  Check in (web_app button)
       check screen: GPS read at once, map, "35 m from Mean Chey ✅"  →  Confirm  →  the Attendance page
07:10  recorded: late 10 min  →  "✅ Checked in — morning shift, 07:10 (late 10 min)"
       (06:40 → "✅ Checked in — morning shift, 06:40 (20 min early)")
07:45  everyone without a morning record → absent (scheduler; no check-out expected)
12:00  reminder "You can check out of the morning shift until 12:59"  →  Check out
12:25  "👋 Checked out — morning shift, 12:25 (+25 min overtime)"
13:00  open morning records → forgot check-out (scheduler)
```

### 22.1 Who is tracked

- **Active staff and supervisors**, never the general manager or the superadmin, on the **tracked days** of their workplace: the weekdays of that day's schedule version (default Monday–Sunday) that no holiday covers (§22.14).
- Each is assigned to **one workplace** (`users.workplace_id`, `UserOut.workplace = {id, name}`). The migration backfilled every staff member and supervisor with the default workplace. Create, edit and role change (`POST /users`, `PATCH /users/{id}`, `POST /users/{id}/role`) accept `workplace_id` (an active workplace; `404 ATTENDANCE_WORKPLACE_NOT_FOUND`, `409 WORKPLACE_ARCHIVED`; for other roles `422 VALIDATION_ERROR`); without it a new or re-roled employee keeps an active workplace or gets the **default**. Reactivation keeps the workplace while it is active, else the default. A change to general manager keeps the link (unused while not tracked). Bootstrap fills any missing one. `GET /users?workplace_id=` lists the staff and supervisors assigned to a workplace.
- Check-in needs **no permission**: being tracked is enough. Anyone else → `403 ATTENDANCE_NOT_REQUIRED`.
- **Who is tracked on a date** (`app/attendance/tracking.py`, the one helper the scheduler, check-in, `me/today`, the bot, the Today view and the summaries all use): the role is staff or supervisor, the account is active, the date is on or after `users.attendance_start_date`, and the date is **not inside an untracked period** — plus the workplace's day-off rules (§22.14). Before the start date the employee is *not started*; a supervisor switched off (`users.attendance_tracked = false`) is *not tracked* from the day it was switched off.
- **Untracked periods** (`attendance_untracked_periods`: `user_id`, `from_date`, `to_date` null = ongoing, `set_by`, `created_at`): turning a supervisor's tracking **off** opens a period from **today** — records already made today are kept, windows that haven't closed yet today are no longer tracked (no reminders, no absent, no forgot check-out; waiting reminders are skipped); turning it **on** closes the period at **yesterday** (or removes it when it began today) and tracking resumes from today. The history stays: those days read "Not tracked" in the summaries.

### 22.2 Workplaces and their schedules

**Each workplace has its own schedule per date**: a **version** (`attendance_schedule_versions`, §22.14) holds the tracked weekdays, the two shifts (one `morning` and one `afternoon`, in JSONB) and the rules; the schedule on a date is the latest version with `effective_from` ≤ that date (dates before the first version use the first). The seeded default workplace **Mean Chey** has the default schedule, every day. Times are local in `BUSINESS_TIMEZONE`; closing times are exclusive (the last minute is shown as "until").

| Shift | Start–End | Check-in window | Late | Absent (refused) | Check-out window | Forgot check-out |
|---|---|---|---|---|---|---|
| Morning (`morning`) | 07:00–12:00 | 06:30–07:44 | after 07:00 | from 07:45 | 12:00–12:59 | from 13:00 |
| Afternoon (`afternoon`) | 13:00–15:00 | 12:30–13:44 | after 13:00 | from 13:45 | 15:00–15:59 | from 16:00 |

- **Windows derive from the shift times and the workplace's rules:** check-in `[start − open_before, start + absent_after)`; check-out `[end, end + checkout_window + 1 min)`. Defaults: **open before 30**, **absent after 45**, **check-out window 59** minutes; **reminders on**; **count early check-in** and **count overtime** on (§22.8); radius 100 m.
- **Validation** per workplace (`VALIDATION_ERROR`, `details.fields` naming the shift or rule): both shifts given once; start < end; the shifts don't overlap; every window stays within the day; check-in closes by the end of the shift; the two check-in windows don't overlap, nor the two check-out windows (a morning check-out may overlap the afternoon check-in, 12:30–12:59); 0 < open before ≤ 120; 0 < absent after ≤ 240; 0 ≤ check-out window ≤ 180; accuracy 10–500 m.
- **Workplaces:** name (unique among active ones, case-insensitive: `409 WORKPLACE_NAME_TAKEN`), address, latitude / longitude (6 decimals, null until set: check-in is refused with `ATTENDANCE_WORKPLACE_NOT_SET`), radius 10–5000 m, `is_default` (exactly one active default; it needs a location to become the default).
  - **Create** copies the default workplace's **current** version (weekdays, shifts and rules) as its first version, from the creation day (upcoming versions aren't copied).
  - **Make default** (`is_default: true`) unsets the previous one; new employees get the default when no workplace is chosen. Nobody is moved.
  - **Delete:** refused for the default (`409 WORKPLACE_IS_DEFAULT`) and while active employees are assigned (`409 WORKPLACE_IN_USE`, `details.employees`). With attendance history it is **archived** (`is_active = false`, `archived_at`; records keep their `workplace_id`; its name is free again); without, deleted (inactive users pointing to it lose the link). Archived workplaces can't be edited, assigned or scheduled (`409 WORKPLACE_ARCHIVED`, also as a Scheduling target) until **restored**. An employee whose workplace is archived checks in at the default one.
- **Schedule changes** are made in **Scheduling** (§22.14) for one, several or all workplaces, from a chosen date (`PUT /attendance/workplaces/{id}/schedule` is gone). Workplace responses carry the current version read-only (`schedule`: `id`, `effective_from`, `weekdays`, both shifts with their windows, the rules, `created_by` / `created_at`). Records keep a snapshot of their shift's `scheduled_start` / `scheduled_end`, so later changes never rewrite history (a correction's late minutes use the snapshot).

### 22.3 Today's state and the one next action

`GET /attendance/me/today` (tracked employees): `server_time`, `timezone`, `work_date`, the employee's `workplace` (name, lat / lng, radius, `has_coordinates`) for the map, both shifts **of that workplace** (start / end, the windows as instants, `phase`: `upcoming` | `check_in_open` | `in_progress` | `check_out_open` | `closed`, and the record), and **`next_action`**:

- `action`: `check_in` | `check_out` | `none`, with `shift_code`, `until` (the last minute) and `closes_at`;
- when nothing is open: `next_action`, `next_shift_code` and `next_opens_at` (today, or tomorrow's morning check-in).

A pending **check-out comes first**: from 12:30 to 12:59 someone checked into the morning gets `check_out` (morning) until it's done, then `check_in` (afternoon). The Mini App shows only this one action.

**Not started / not tracked:** before the employee's start date `me/today` has `next_action = none`, no shifts and `starts_on` (the start date); for a supervisor switched off `tracked = false` (else `true`, `starts_on` null), `next_action = none`. (Check-in and check-out are refused as in §22.4.)

**Days off:** `day_off` is `{reason: holiday | weekday, holidays: [{id, name_km, name_en}]}` (else null). On a day off `shifts` is empty and `next_action` is `none` with the **next tracked** opening (`next_opens_at`, looked up to 400 days ahead); on other days "tomorrow" is also the next tracked day.

### 22.4 Check-in and check-out

`POST /attendance/check-in` and `POST /attendance/check-out` with `{latitude, longitude, accuracy_m}` from the phone's GPS. **Time is always the server's** (`app/attendance/clock.py`); the server picks the shift from the employee's workplace schedule. Checks, in this order:

1. not tracked → `403 ATTENDANCE_NOT_REQUIRED` (not staff / supervisor, deactivated, or a supervisor switched off); before the start date → `409 ATTENDANCE_NOT_STARTED` (`details.start_date`);
2. the employee's workplace is missing or has no coordinates → `409 ATTENDANCE_WORKPLACE_NOT_SET`;
3. a day off at that workplace (§22.14) → `409 ATTENDANCE_DAY_OFF` (`reason`, `holidays`, `next_opens_at`, `next_shift_code`), for check-in and check-out;
4. the time window:
   - check-in: before the first window → `409 ATTENDANCE_TOO_EARLY` (`details.opens_at`, `shift_code`); from a shift's cutoff until its end → `409 ATTENDANCE_CHECKIN_CLOSED` (`shift_code`, `closed_at`, `next_opens_at`); otherwise between windows (or after the last shift) → `409 ATTENDANCE_NO_SHIFT_NOW` (`next_opens_at`, `next_shift_code`);
   - check-out: before the shift's end (from its check-in window on) → `409 ATTENDANCE_CHECKOUT_TOO_EARLY` (`opens_at`, `shift_code`); after the window → `409 ATTENDANCE_CHECKOUT_CLOSED` (`shift_code`, `closed_at`);
5. duplicates and order: `409 ATTENDANCE_ALREADY_CHECKED_IN`; a check-out without a check-in (or absent) → `409 ATTENDANCE_NOT_CHECKED_IN`; `409 ATTENDANCE_ALREADY_CHECKED_OUT`;
6. distance (haversine) to the workplace above its radius → `422 ATTENDANCE_TOO_FAR` (`distance_m`, `radius_m`).

The GPS accuracy never refuses a check (since migration 0027; the per-schedule limit is gone): a position inside the radius is accepted however rough the reading, and the accuracy is stored with the record.

Instants in `details` are ISO strings with the business offset. **Every refused attempt is audited** (`attendance.attempt_refused`: action, code, shift, distance and accuracy rounded; committed before the error is returned) and creates no record.

On success:

- **check-in:** `present` when at or before the start (to the minute: 07:00:59 is on time), else `late` with `late_minutes` = whole minutes after the start; `early_minutes` before the start (§22.8); position, accuracy and distance stored; `source = mini_app`;
- **check-out:** `checkout_status = checked_out`, time and position stored, `overtime_minutes` after the end (§22.8);
- the response is `{action, record, today}` (today's state after it);
- the bot sends a **confirmation** to the user's chat after the commit, in their language, with the check-screen button: "✅ Checked in — morning shift, 07:12 (late 12 min)", "✅ Checked in — morning shift, 06:40 (20 min early)" / "👋 Checked out — morning shift, 12:25 (+25 min overtime)", "👋 Checked out — morning shift, 12:00" (nothing when not linked or without a bot).

**Absent and late shifts:**

- An **absent** shift (no check-in by start + absent after) needs **no check-out**: it is never marked forgot check-out, a check-out for it is refused with `409 ATTENDANCE_NOT_CHECKED_IN`, and `next_action` moves straight on to the next shift (whose check-in works as usual).
- A **late** shift still needs its **check-out**; if it's missed, the record stays `late` with `checkout_status = forgot_checkout`.

### 22.5 Records

`attendance_records`, one per (`user_id`, `work_date`, `shift_code`): the workplace it was made at, the **snapshot** of `scheduled_start` / `scheduled_end`, `status` (`present` | `late` | `absent`), `late_minutes`, `early_minutes`, `overtime_minutes`, `early_counts` / `overtime_counts` (the workplace's flags when the record was created), check-in time / lat / lng / accuracy / distance, `checkout_status` (`checked_out` | `forgot_checkout` | null while open), check-out time and position, `source` (`mini_app` | `auto` | `correction`), `corrected`, `correction_reason`, `corrected_by` (a `UserRef`), `corrected_at`. CHECKs: absent ⇔ no check-in; an absent record has no check-out; a check-out time only with `checked_out`.

### 22.6 Scheduler (absent, forgot check-out, reminders)

A background task in the API process, **once a minute**, guarded by a Postgres advisory lock (one worker per tick), idempotent, and catching up on today's passed times after a restart. It is **evaluated per workplace**: each active workplace's windows from its schedule version for the date, for the employees assigned to it (one without an active workplace counts at the default). Only employees active and **tracked on that date** count (§22.1: started, not switched off). **Days off** (§22.14) are skipped: no absents, no forgot check-out, no reminders, and waiting reminders of that workplace's employees are `skipped`. `rerun` replays the passed cutoffs (absent, forgot check-out; never reminders) of given (workplace, date) pairs, used when days become tracked again.

- **Absent:** from a shift's cutoff (start + absent after), an `absent` record (`source = auto`, that workplace) for every tracked employee of the workplace without one **who existed before the cutoff** (someone created at 10:00 isn't absent for the morning).
- **Forgot check-out:** when a workplace's check-out window closes, its open records become `forgot_checkout`.
- **Reminders** (when the workplace's `reminders_enabled`): when a check-in window opens, every tracked employee of that workplace with a linked Telegram account and no record for the shift; when a check-out window opens, those checked in and not out. Each reminder **once** (`attendance_reminders`, unique per user / day / shift / kind), only while its window is open (no catch-up spam after downtime; a stored one whose window closed is `skipped`, and so is one no longer needed or whose workplace turned reminders off); sent after the commit; outcome stored (`sent`, `failed` with the error, `not_linked`, `bot_off`, `skipped`). Reminders and check-in / check-out confirmations use the same binding as alerts: pressing Start in the bot links an employee (§7.4). Texts (the user's language): "🕡 ម៉ោងចុះវត្តមានវេនព្រឹកបានបើកហើយ រហូតដល់ 07:44។" / "🕡 Morning check-in is open until 07:44." and "🕛 You can check out of the morning shift until 12:59.", each with a **ចុះវត្តមាន / Check in** or **ចុះចេញ / Check out** `web_app` button opening the check screen.
- `ATTENDANCE_SCHEDULER_ENABLED` (default `true`) turns it off (the tests run ticks directly).

### 22.7 Corrections

- `PATCH /attendance/records/{id}` fixes a record; `POST /attendance/records` adds a missing one (`user_id`, `work_date` up to today, `shift_code`; the shift's current times at the employee's workplace are snapshotted; `409 ATTENDANCE_RECORD_EXISTS` when the shift has one). Both need a **reason** (1–500) and take `status`, `check_in_time` / `check_out_time` ("HH:MM", local, on the work date) and `checkout_status`:
  - `absent` clears the times and positions;
  - otherwise `check_in_time` is required and **present / late follows from it**, with `late_minutes` recalculated from the record's snapshot start; `checked_out` needs `check_out_time` (not before the check-in; implied when only the time is given); `forgot_checkout` or null clear the check-out;
  - `early_minutes` / `overtime_minutes` are recalculated from the corrected times, the snapshot times and the record's own flags, capped by the open-before / check-out window of the record's workplace's schedule on its date (§22.8). An added record snapshots the flags of that day's schedule (also on a day off: a corrected record is kept, §22.14).
- **Month lock:** while the employee's request for the record's month is `pending` or `approved`, neither a fix nor an added record is allowed in that month → `409 ATTENDANCE_MONTH_LOCKED` (`details.year`, `month`). A rejection unlocks it (§22.15).
- Marks `corrected` with who / when / why; audit `attendance.correct` (`before` / `after`, `reason`, `created`). A fix that changes nothing writes nothing.
- **Scope:** the role hierarchy. The GM and the superadmin fix staff and supervisors, a supervisor (when given Attendance corrections) staff only (`FORBIDDEN_SCOPE`); a user who isn't tracked → `422 ATTENDANCE_NOT_REQUIRED`; an unknown record → `404 ATTENDANCE_RECORD_NOT_FOUND`.

### 22.8 Early check-in and overtime

- **Early** = scheduled start − check-in (in whole minutes, from the minute shown: 06:40:30 is 20 min early for 07:00), else 0; at most `open_before_min`.
- **Overtime** = check-out − scheduled end (whole minutes: 12:25:40 is 25), else 0; at most `checkout_window_min`. Forgot check-out or no check-out → 0.
- Each workplace switches them: **`count_early_checkin`** and **`count_overtime`** (default on), part of the schedule version (Scheduling, `attendance.scheduling`). A record **snapshots** both flags when it's created (`early_counts`, `overtime_counts`); with a flag off its minutes are stored as 0. A later change affects new records only.
- Computed at check-in / check-out and on corrections (§22.7). Migration 0019 backfilled existing records from their snapshot times (capped by their workplace's windows; flags on).

### 22.9 Summary (my attendance, an employee's attendance)

`GET /attendance/me/summary?year=YYYY&month=MM` (tracked employees) and `GET /attendance/users/{id}/summary?year=&month=` (`attendance.view`, the corrections scope: GM / superadmin → staff and supervisors, a supervisor → staff; hidden accounts 404, outside the scope `FORBIDDEN_SCOPE`, untracked roles `422 ATTENDANCE_NOT_REQUIRED`). `month` omitted → the **whole year**; no parameters → the **current month** in `BUSINESS_TIMEZONE`. A future period, a month outside 1–12 or a year before 2000 → `VALIDATION_ERROR`.

Every figure comes from the records (their snapshot times and stored minutes, corrected values when corrected); only recorded shifts count (today's once it has a record), and **records on days off** (kept corrected ones) **don't count**:

| Figure | Definition |
|---|---|
| scheduled minutes (per record) | `scheduled_end − scheduled_start` |
| **present** | `present` + `late` records (`total_shifts`, `by_shift`); minutes = Σ (scheduled − late + early + overtime) |
| **absent** | `absent` records; minutes = their scheduled minutes |
| **late** | `late` records (`count`), Σ `late_minutes` |
| **early** / **overtime** | records with minutes > 0 (`count`), Σ minutes |
| `missing_minutes` | absent minutes + late minutes |
| `extra_minutes` | early + overtime minutes |
| `balance_minutes` | extra − missing (signed) |
| `forgot_checkout` | records with `checkout_status = forgot_checkout` |

Response: `timezone`, `period` (`year`, `month` or null, `start`, `end` = the last day listed, at most today), `employee` (`user` `UserRef`, `role`, `position`, `is_active`, `workplace`, `since` = the attendance start date, for accounts from before it the creation date), `shifts` (code and names, from the employee's workplace), `kpis`, and `days`: **newest first**, one per date from the period start (or the `since` date, if later; **days before the start date are omitted**) to **today** (no future dates; a past period in full), each with `not_tracked` (true inside an untracked period: shown as "Not tracked", its kept records are listed but **excluded from the KPIs**), `day_off` (null, or why it isn't tracked: at the workplace of that day's records, else the employee's current one) and per shift `{code, status: present | late | absent | none, record}` (`none`: no record yet; the record carries the times, the late / early / overtime minutes, `checkout_status` and the correction).

**Requests in the summary:** for a monthly period the summary also has `request` (the month's request or null: `id`, `status`, `type`, requested and approved splits, `approved_with_changes`, `review_comment`, `reject_reason`, `submitted_at`, `reviewed_by` (`UserRef`), `reviewed_at`), `request_eligibility` (`eligible` \| `not_needed` \| `window_not_open` \| `window_closed`) and `month_locked` (a pending or approved request). A whole year has `request = null`, `request_eligibility = null`, `month_locked = false`.

### 22.10 Endpoints

| Method | Path | Guard | Notes |
|---|---|---|---|
| GET | `/attendance/me/today` | tracked employee | §22.3 |
| GET | `/attendance/me/summary?year=&month=` | tracked employee | §22.9 |
| GET | `/attendance/users/{id}/summary?year=&month=` | `attendance.view` + scope | §22.9 |
| GET, POST | `/attendance/requests/me`, `/attendance/requests` | tracked employee | Requests: §22.15 |
| GET | `/attendance/requests`, `/attendance/requests/{id}`, `/attendance/settings/requests` | `attendance.requests_review` (the employee reads their own) | §22.15 |
| POST | `/attendance/requests/{id}/approve`, `/attendance/requests/{id}/reject` | `attendance.requests_review` + scope | §22.15 |
| PUT | `/attendance/settings/requests` | superadmin | §22.15 |
| POST | `/attendance/check-in`, `/attendance/check-out` | tracked employee | §22.4 |
| GET | `/attendance/day?date=&workplace_id=` | `attendance.view` | Default today, all workplaces. `day_off` (the filtered workplace's, else the default's) and per workplace / row `day_off`; on a day off a row's cells are `day_off` (a kept corrected record is `recorded`) and count nothing. `shifts`: per shift `kpis` (`expected`, `present`, `late`, `absent`, `not_yet` (no record, check-in still possible), `no_record` (past the cutoff without one), `checked_out`, `forgot_checkout`) and `phase`, over every row shown (times of the filtered workplace, else the default's). `workplaces`: the same per workplace with its own shift times. `workplace_options`: active workplaces (the filter). `starts_later` and `not_tracked`: employees in scope who are **not expected** that day — attendance starts after it (rows carry `starts_on`) / a supervisor not tracked — in no KPI and not in `rows`; their cells hold only records already made. One row per employee in the viewer's scope (GM: staff and supervisors; supervisor: staff; those active that day and tracked, plus anyone with a record): `user`, `role`, `position`, `is_active`, `workplace` (that day's records' workplace, else the current one), and per shift `{state: recorded \| not_yet \| no_record, record}`, evaluated with that workplace's schedule. Supervisors first, then by name. Unknown `workplace_id` → 404. |
| PATCH, POST | `/attendance/records/{id}`, `/attendance/records` | `attendance.correct` | §22.7 |
| GET | `/attendance/workplace-options` | `users.view` or any workplace permission | Active workplaces `{id, name, is_default}`, default first: the user form's select and the users list filter. |
| GET | `/attendance/workplaces?include_archived=` | any workplace permission (`workplace_view`, `workplace_update`, `workplace_manage`) | Each: name, address, lat / lng (6 decimals), radius, `has_coordinates`, `is_default`, `is_active`, `archived_at`, `schedule` (the current version, read-only: weekdays, the rules, both shifts with their windows (`check_in_opens`, `check_in_until`, `late_after`, `absent_from`, `check_out_opens`, `check_out_until`, `forgot_from`)), `employee_count` (active staff and supervisors), `has_history`, `created_by` / `updated_by`. |
| GET | `/attendance/workplaces/{id}` | same | The same plus `employees` (active staff and supervisors assigned: `user`, `role`, `position`). |
| POST | `/attendance/workplaces` | `attendance.workplace_manage` | Name, address, lat / lng, radius (default 100); the schedule is a copy of the default workplace's current version, from today. Audit `workplace.create`. |
| PATCH | `/attendance/workplaces/{id}` | `attendance.workplace_update` (Record); `is_default` also needs `attendance.workplace_manage` (403 `MISSING_PERMISSION`, `required: ["attendance.workplace_manage"]`, nothing saved) | Name, address, `latitude` + `longitude` together (null clears both), `radius_m` 10–5000, `is_default: true`. Audit `workplace.update` (`changes`, incl. `previous_default`). |
| DELETE | `/attendance/workplaces/{id}` | `attendance.workplace_manage` | `{result: archived \| deleted}` (§22.2). Audit `workplace.archive` / `workplace.delete`. |
| POST | `/attendance/workplaces/{id}/restore` | `attendance.workplace_manage` | Audit `workplace.restore`. |
| GET, PUT, POST, PATCH, DELETE | `/attendance/scheduling…`, `/attendance/calendar`, `/attendance/holidays…` | view: `attendance.view` or `attendance.scheduling`; writes: `attendance.scheduling` | Scheduling: §22.14. (`PUT /attendance/workplaces/{id}/schedule` was removed.) |

User references are `UserRef`s (redacted, §13); the routes are in the redaction and superset sweeps.

### 22.11 Access

| Feature | Menu | Applies to | Levels | Defaults |
|---|---|---|---|---|
| `attendance` (Attendance) | attendance | GM, supervisor | Off · View only (`attendance.view`) | GM View, supervisor Off |
| `attendance_corrections` | attendance | GM, supervisor | Off · Full access (`attendance.correct`) | GM Full, supervisor Off |
| `attendance_workplace` (Workplaces) | attendance | **GM** (set by the superadmin) | Off · View only (`attendance.workplace_view`) · Record (`+ attendance.workplace_update`: edit existing workplaces — name, address, map position, radius) · Full access (`+ attendance.workplace_manage`: also create, delete / archive, restore, make default) | GM View |
| `attendance_scheduling` (Attendance scheduling) | attendance | GM, supervisor (**grantor must hold it**) | Off · Full access (`attendance.scheduling`: tracked weekdays, holidays, shift times and rules, §22.14) | GM Off, supervisor Off |
| `attendance_requests` (Attendance requests) | attendance | GM, supervisor | Off · Full access (`attendance.requests_review`: approve, approve with changes or reject, §22.15) | GM Full, supervisor Off |

The superadmin holds them implicitly; the new permissions were backfilled per these defaults (§5.1). **Attendance scheduling**: the superadmin turns it on or off for GMs (Access tab); a GM holding it can give it to supervisors; GMs without it never see it (`FEATURE_NOT_FOUND`); no cascade on revoke. Viewing Scheduling (calendar, holidays, weekdays and schedule, read-only) needs `attendance.view` or `attendance.scheduling`. Staff get no attendance permission: they check in as tracked employees, and these features don't apply to them (so a supervisor's Staff access can't give them).

### 22.12 Bot

- **No attendance commands** (`/checkin` / `/checkout` aren't registered or handled). The entry points are buttons:
  - **`/start`**: binds an unlinked account by username first (§7.4). For a linked Telegram account of a **tracked employee** (tracked today, or whose attendance starts later; not a supervisor switched off) the greeting has two `web_app` buttons side by side, **🍗 បើកកម្មវិធី / Open app** and **🕒 វត្តមាន / Attendance** (→ `MINI_APP_URL/attendance/check`, the check screen, which decides the action). Everyone else (general managers, deactivated accounts, unlinked chats) keeps only Open app.
  - **Menu button:** registration sets the bot's default menu button to a `web_app` button **បើកកម្មវិធី** → `MINI_APP_URL` (the default button when it isn't HTTPS); `/start` and `/lang` set it for that chat in the user's language (**Open app** in English). `MINI_APP_URL` is part of the registration fingerprint, so it's set once and refreshed when the URL changes; polling mode sets it at startup.
  - **Reminders** and **confirmations** carry the check-screen button; the Home card opens it too.
- If `MINI_APP_URL` isn't HTTPS, the buttons are omitted and the bot says the app isn't configured.

### 22.13 Limits

- The position comes from the phone; **fake-GPS apps** can't be detected from a web app. The radius, the server's clock, the stored accuracy and the audit of refused attempts (distance, accuracy) make cheating visible, not impossible.
- Days off are whole days per workplace (no per-shift holidays, rotas or per-person shifts); two shifts per workplace. Snapshots, versions and stable shift codes leave room for more.

### 22.14 Scheduling (tracked weekdays, holidays, shift schedule)

**Attendance → Scheduling** is the one place to manage, for **one workplace, several or all**: the tracked weekdays, holidays (days with no attendance) and the shift schedule and rules.

**Schedule versions** (`attendance_schedule_versions`, unique per `workplace_id` + `effective_from`): `weekdays` (ISO, Monday = 1 … Sunday = 7, at least one), `shifts` (JSONB: `code`, `name_km`, `name_en`, `start_time`, `end_time` "HH:MM", `position`; codes stay `morning` / `afternoon` across versions), `open_before_min`, `absent_after_min`, `checkout_window_min`, `count_early_checkin`, `count_overtime`, `reminders_enabled`, `created_by` / `created_at`. The schedule of a workplace on a date is the latest version with `effective_from` ≤ that date (before the first: the first). Migration 0020 turned each workplace's shifts and rule columns into one version from its creation date (business time zone) with all seven weekdays, then dropped `attendance_shifts` and the columns.

**Changes apply from a date** (`effective_from`, default today; a past date → `VALIDATION_ERROR`):

- A write creates the version on that date for every target workplace (a copy of the one in effect then, with the changed fields), or **replaces** the version already on that date. The same fields are also written into that workplace's **later upcoming versions**, so the change holds from that date on (`changes.later_versions` in the audit). A workplace where nothing changes is skipped; nothing changed anywhere → no audit entry.
- **Upcoming versions** (`effective_from` > today) can be deleted; current or past ones → `409 ATTENDANCE_SCHEDULE_VERSION_IN_EFFECT`.
- A change effective **today** that alters today's shift times leaves records already made with their snapshots; the new times apply to windows that haven't opened yet.
- `workplace_ids` is a list of active workplaces or `"all"` (every active workplace at that moment; unknown → 404, archived → `409 WORKPLACE_ARCHIVED`). One transaction for all targets, holding the scheduler's advisory lock (no tick in between).

**Holidays** (`attendance_holidays`: `name_km`, `name_en`, `start_date`, `end_date` (≥ start, at most 31 days), `scope` `all` | `selected`, `note` (≤ 500), created / updated by / at; `attendance_holiday_workplaces` for `selected`). `all` also covers workplaces created later. Whole days only.

**A day is not tracked** at a workplace when its weekday isn't in that day's version's `weekdays`, or a holiday covers it (`all`, or `selected` including that workplace). On such days: no reminders, no automatic absent, no forgot check-out; check-in / check-out → `409 ATTENDANCE_DAY_OFF`; `me/today` shows `day_off` and the next tracked opening; the day view and summaries don't count them (expected / present / absent).

**Retroactive effects.** Every holiday write and every weekday change effective today compares the (workplace, date ≤ today) pairs that are days off before and after it:

- **newly off** (adding a holiday for today or earlier, widening one, untracking today's weekday): the records on those dates made at those workplaces (`attendance_records.workplace_id`) are **deleted** (auto absents and real check-ins alike) **except corrected ones** (`corrected = true`, kept; they show but don't count). One `attendance.records_removed_by_day_off` entry holds the removed records' snapshots. Records of an **employee-month locked by a request** (§22.15) are **never removed** and absents are **not recreated** for them; the response counts them in `skipped_locked` (`SchedulingWriteOut`, `HolidayWriteOut`, `HolidayCopyOut`).
- **back on** (removing or shortening a holiday, tracking today again): the scheduler replays those dates' passed cutoffs and recreates absents where there is no record (no reminders for past windows).
- Future dates need no cleanup. Write responses say how many records were removed (`records_removed`) and absents recreated (`absents_recreated`).

**Copy from last year:** `POST /attendance/holidays/copy {from_year, to_year}` copies every holiday starting in `from_year` to the same month / day in `to_year` (Feb 29 → Feb 28; a range crossing New Year keeps its length), same names, scope, workplaces and note; one that would duplicate a holiday with the same name (km or en) and dates is skipped. Returns `{created, skipped, records_removed}`. Khmer holidays move each year, so dates are then adjusted.

| Method | Path | Guard | Notes |
|---|---|---|---|
| GET | `/attendance/scheduling?workplace_ids=` | `attendance.view` or `attendance.scheduling` | Repeat `workplace_ids` (omit = all active). `today`, `timezone`, per workplace `current` and `upcoming` versions (with windows), `differs: {weekdays, shifts}` (the chosen workplaces' current versions differ), `workplace_options` (every active workplace). |
| PUT | `/attendance/scheduling/weekdays` | `attendance.scheduling` | `{workplace_ids \| "all", weekdays, effective_from?}` → `{scheduling, records_removed, absents_recreated}`. Audit `attendance.weekdays_update`. |
| PUT | `/attendance/scheduling/shifts` | `attendance.scheduling` | `{workplace_ids \| "all", shifts (both), open_before_min, absent_after_min, checkout_window_min, count_early_checkin, count_overtime, reminders_enabled, effective_from?}`, validated as one day (§22.2) → same response. Audit `attendance.schedule_update`. |
| DELETE | `/attendance/scheduling/versions/{id}` | `attendance.scheduling` | Upcoming only (204). Audit `attendance.schedule_version_delete`. |
| GET | `/attendance/calendar?year=&month=&workplace_ids=` | `attendance.view` or `attendance.scheduling` | Per day: `status` `tracked` \| `off` \| `mixed`, `day_off` (when off everywhere: the first workplace's reason), `holidays` covering any chosen workplace, and per workplace `day_off` when several are chosen. |
| GET | `/attendance/holidays?year=&workplace_id=`, `/attendance/holidays/{id}` | `attendance.view` or `attendance.scheduling` | Holidays overlapping the year (default this year), by start date; `workplace_id`: those covering it. Each: names, dates, `days`, `scope`, `workplaces` (selected), `note`, created / updated by / at. |
| POST, PATCH | `/attendance/holidays`, `/attendance/holidays/{id}` | `attendance.scheduling` | `{name_km, name_en, start_date, end_date, scope, workplace_ids? (selected), note}` (PATCH: the whole holiday) → `{holiday, records_removed, absents_recreated}`. Audit `attendance.holiday_create` / `holiday_update`. |
| DELETE | `/attendance/holidays/{id}` | `attendance.scheduling` | → `{holiday: null, records_removed, absents_recreated}`. Audit `attendance.holiday_delete`. |
| POST | `/attendance/holidays/copy` | `attendance.scheduling` | Above. Audit `attendance.holiday_copy`. |

All write responses (`records_removed`, `absents_recreated`) also carry `skipped_locked`: records and absents left alone because the employee's month is locked by a pending or approved request (§22.15).

User references (`created_by`, `updated_by`) are redacted `UserRef`s (§13); the routes are in the redaction and superset sweeps. Access: §22.11.

### 22.15 Requests (monthly missing time)

After a month ends, a tracked employee whose **missing time is at least 1 hour** sends **one request** for it, saying how it will be covered: a **salary cut**, **unpaid extra work** or **both**. A reviewer approves, approves with changes or rejects. Fulfilment (payroll, doing the extra work) happens **outside the app for now**: the app records what was agreed and everyone involved sees it.

- **Missing time** = the month's `balance_minutes` (extra − missing, §22.9) when negative, as a positive number (`app/attendance/requests.py`). Eligible at **60 minutes or more**; under that → `not_needed`, no request (`409 ATTENDANCE_REQUEST_NOT_NEEDED` if one is sent).
- **Window:** from the **1st of the following month** (`BUSINESS_TIMEZONE`) to the **deadline day** of that month, inclusive. The deadline is the setting `request_deadline_day` (1–28, **default 7**, stored in `app_settings`, edited by the superadmin with `PUT /attendance/settings/requests`). Outside it, and for the current or a future month → `409 ATTENDANCE_REQUEST_WINDOW_CLOSED` (`details.opens`, `closes`). A month's eligibility: `window_not_open` (it hasn't ended), `not_needed`, `eligible` or `window_closed`; an eligible month that is closed with no request reads **No request** (no automatic action).
- **One request per employee and month** (unique `user_id`, `year`, `month`). After a **rejection** no new request for that month (`409 ATTENDANCE_REQUEST_EXISTS`, which is checked before the window). The employee can't edit or withdraw it.
- **Content:** `salary_cut_minutes` ≥ 0 and `unpaid_work_minutes` ≥ 0 whose **sum equals the missing time** (`422 ATTENDANCE_REQUEST_SPLIT_MISMATCH`, `details.expected` / `given`), optional `note` (≤ 500). `type` is derived from the requested split: `salary_cut`, `unpaid_work` or `both`.
- **Snapshot:** `missing_minutes`, `extra_minutes`, `absent_minutes`, `late_minutes` and `balance_minutes` of the month are stored at submission: the request keeps showing them even if the month's records change later (after a rejection unlocks it).
- **Month lock:** while a request is `pending` or `approved`, the employee's records in that month can't be corrected or added (`409 ATTENDANCE_MONTH_LOCKED`, §22.7), and holiday / weekday changes skip them (`skipped_locked`, §22.14); the scheduler doesn't recreate absents for them either. A **rejection unlocks** the month. Summaries report `month_locked` (§22.9).
- **Review** (`pending` only, otherwise `409 ATTENDANCE_REQUEST_NOT_PENDING`; the row is locked, so two reviewers can't both decide):
  - **Approve** with no split: as submitted. `approved_*_minutes` are filled.
  - **Approve with changes:** `salary_cut_minutes` and / or `unpaid_work_minutes` (the other one defaults to the rest of the missing time), sum = the snapshot's missing time (else `ATTENDANCE_REQUEST_SPLIT_MISMATCH`) and an optional `comment`. The requested and the approved split are **both stored**; `approved_with_changes` is true when the approved split differs from the requested one.
  - **Reject:** `reason` is required (1–500).
  - A reviewer can't review their own request (`403 FORBIDDEN_SCOPE`).
- **Scope:** the role hierarchy. GMs and the superadmin review staff and supervisors; a supervisor with `attendance.requests_review` reviews staff only (`FORBIDDEN_SCOPE` otherwise). The list and the pending count only include employees in scope.
- **Notifications** (§16; Telegram when linked, plus the bell): *submitted* → the reviewers in scope (holders of `attendance.requests_review` whose scope includes the employee, plus the superadmin); *approved* / *rejected* → the employee; a **reminder** on the 1st of the month to every tracked employee whose previous month has an eligible balance and no request, **once** (the scheduler's first tick of the 1st; the month is recorded in `app_settings` `attendance.request_reminder_month`, and an employee already reminded isn't reminded again).
- **Access:** the employee needs no permission for their own requests (`GET /attendance/requests/me`, `POST /attendance/requests`, `GET /attendance/requests/{id}`). Reviewing needs `attendance.requests_review` (Attendance requests feature, §22.11): **GM Full, supervisor Off**. The superadmin holds it implicitly.

| Method | Path | Guard | Notes |
|---|---|---|---|
| GET | `/attendance/requests/me?year=` | tracked employee | Per month of the year (newest first, up to the current month, from the month attendance started): `balance_minutes`, `missing_minutes`, `extra_minutes`, `absent_minutes`, `late_minutes`, `eligibility`, `opens`, `closes`, `request`. Also `request_deadline_day`. |
| POST | `/attendance/requests` | tracked employee | `{year, month, salary_cut_minutes, unpaid_work_minutes, note?}` → `201` request. Checks, in order: exists → window → needed → split. Audit `attendance.request_submit`. |
| GET | `/attendance/requests?status=&year=&month=&user_id=&page=` | `attendance.requests_review` | In scope, **pending first (oldest first)**, then the rest newest first; 20 per page; `pending_count`. `status=no_request`: eligible months whose window is over with no request, for the chosen year / month (default: the last 3 closed months), one row per employee and month (`id` null). |
| GET | `/attendance/requests/{id}` | the employee, or `attendance.requests_review` + scope | The request with the snapshot, both splits, the review and `month_locked`. Unknown → `404 ATTENDANCE_REQUEST_NOT_FOUND`. |
| POST | `/attendance/requests/{id}/approve` | `attendance.requests_review` | `{salary_cut_minutes?, unpaid_work_minutes?, comment?}`. Audit `attendance.request_approve`. |
| POST | `/attendance/requests/{id}/reject` | `attendance.requests_review` | `{reason}`. Audit `attendance.request_reject`. |
| GET | `/attendance/settings/requests` | `attendance.requests_review` | `{request_deadline_day}` |
| PUT | `/attendance/settings/requests` | superadmin | `{request_deadline_day}` (1–28). Audit `attendance.settings_update`. |

Every user reference (`user`, `reviewed_by`) is a `UserRef` (§13); the routes are in the redaction and superset sweeps. Data: `attendance_requests` (migration `0022`).
