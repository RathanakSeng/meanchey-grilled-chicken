# UI Features — Phase 1

What the Mean Chey Grilled Chicken UI (មាន់អាំងមានជ័យ) offers today. One React app serves both the **PC dashboard** and the **Telegram Mini App**.

Phase 1 covers sign-in, user management and permission control only.

> The UI hides what a user can't do, for a cleaner experience. **The API enforces every rule**, so hiding things in the UI is never the security boundary.

- [1. Two experiences, one app](#1-two-experiences-one-app)
- [2. Sign-in](#2-sign-in)
- [3. Forced password change](#3-forced-password-change)
- [4. App shell and navigation](#4-app-shell-and-navigation)
- [5. Home](#5-home)
- [6. Production](#6-production)
- [7. Settings](#7-settings)
- [8. Users](#8-users)
- [9. User detail](#9-user-detail)
- [10. Permissions tab](#10-permissions-tab)
- [11. Audit log](#11-audit-log)
- [12. My profile](#12-my-profile)
- [13. Language (Khmer / English)](#13-language-khmer--english)
- [14. Error and status screens](#14-error-and-status-screens)
- [15. Screen access matrix](#15-screen-access-matrix)

---

## 1. Two experiences, one app

| | PC dashboard | Telegram Mini App |
|---|---|---|
| Opened from | Browser | The bot's **Open app** button or menu button |
| Sign-in | Username + password | Automatic, using Telegram `initData` |
| Layout | Left sidebar + top bar | Top bar + bottom navigation, full-height, safe-area aware |
| Navigation | Sidebar: Home · Production · Settings (with its sub-pages nested) | Bottom bar: Home · Production · Settings |
| Back navigation | In-page back arrows (to the parent screen) | Telegram's native **Back** button (to the parent screen), plus in-page arrows |
| Lists | Tables | Cards |

- The mobile layout is used inside Telegram, **or** on any screen narrower than 768 px.
- A phone browser gets the same experience as the Mini App, minus the automatic sign-in.

## 2. Sign-in

### PC (password)

- Fields: **Username** and **Password**.
  - The username is the Telegram username, with or without `@`, in any case.
  - The superadmin uses `superadmin`.
- A hint reminds first-time users that their initial password is their Telegram username.
- Errors are translated:
  - wrong credentials;
  - account locked, showing the local time the lock ends;
  - account deactivated;
  - server unreachable.
- A language switcher is available before signing in.
- After signing in, users return to the page they originally requested.

### Telegram Mini App (automatic)

- On launch the app signs in with Telegram automatically; a spinner shows meanwhile.
- **If it succeeds,** the app applies the user's saved language and goes to Home. If a password change is pending, it goes to that screen instead.
- **If it fails,** a translated explanation is shown.
  - The most common case is "This Telegram account isn't registered — ask your manager to create an account with your Telegram username".
  - The screen offers **Try again** and **Sign in with a password instead**.
- The login page inside Telegram also shows a **Continue with Telegram** button.

## 3. Forced password change

Everyone except the superadmin must set their own password:

- on first sign-in;
- after a manager resets their password.

On this screen:

- It explains why the change is required.
- It asks for the **current password** (with a hint that it is the Telegram username on first login), the **new password** and a **confirmation**.
- It checks the rules before submitting:
  - at least 8 characters;
  - not the same as the username;
  - both new passwords match.

  The same rules are enforced by the server.
- Every other page redirects here until the password is changed.
- **Log out** is available.
- The language switcher works here but applies locally only. The profile can't be saved until the password is changed.

## 4. App shell and navigation

The app is organized in two sections under Home:

```
Home                      everyone
├── Production            everyone          /production
└── Settings              everyone          /settings
    ├── Users             users.view        /settings/users
    ├── Audit log         superadmin, GM    /settings/audit-logs
    └── My profile        everyone          /settings/profile
```

- **Each item appears only when the user is allowed to open it.** The rules are unchanged from before: Users needs `users.view`, and Audit log is for the superadmin and general manager.
- **Settings is always shown,** because everyone can open My profile.
- **Staff** see Home, Production and Settings. Inside Settings they see only My profile, which follows from the permissions with no special handling.
- **Desktop sidebar:** Home, Production and Settings.
  - While you're anywhere under Settings, its visible sub-pages are listed indented below it.
  - The current page and its section are highlighted.
- **Mobile / Telegram bottom bar:** exactly three buttons, Home · Production · Settings. Settings stays highlighted on every Settings page.
- **Back buttons,** both in-page and Telegram's native one, go to the **parent screen**, not the browser history. For example: user details → Users → Settings → Home. A deep link opened straight into the Mini App therefore still has a sensible way back.
- **Header:** language switcher (ខ្មែរ / EN) and an avatar menu.
- **Avatar menu:** name, role, Telegram username, **My profile** and **Log out**.
- **Permission changes show up quickly.** Menus refresh when Home or Settings is opened and the cached permissions are more than a minute old. They also refresh whenever the server answers "no permission", "wrong role" or "out of scope".
- **Old links keep working.** Old addresses (`/users/…`, `/audit-logs`, `/profile`) redirect to their new place under `/settings`, keeping the rest of the address, for example `/users/<id>?tab=permissions`.

## 5. Home

- A welcome banner with the user's name and role badge (plus position for staff).
- Two large tiles, each with an icon, a title and a one-line description. They sit side by side on desktop and stack on mobile:
  - **Production:** day-to-day production and operations;
  - **Settings:** users, permissions and your account.

## 6. Production

**Path:** `/production`. **Who can open it:** everyone.

Phase 1 has no production features yet, so the page shows "Production features are coming soon". New production features will appear here as cards or sub-pages.

## 7. Settings

**Path:** `/settings`. **Who can open it:** everyone.

- A hub with one card per Settings page the user may open. Each card has an icon, a title and a one-line description:

  | Card | Shown to |
  |---|---|
  | Users | holders of `users.view` |
  | Audit log | superadmin, general manager |
  | My profile | everyone |

- The cards come from the same menu definition as the sidebar, so a new Settings page appears here automatically.

## 8. Users

**Path:** `/settings/users` (create: `/settings/users/new`). **Who can open it:** users with `users.view`. The list only contains users the viewer manages:

| Viewer | Sees |
|---|---|
| Superadmin | general manager, supervisors, staff |
| General manager | supervisors, staff |
| Supervisor | staff |

**List**

- Search by name, Telegram username, phone or position. It is debounced as you type.
- Filters:
  - **role**: only roles the viewer manages;
  - **position**: a list of the positions actually in use in the viewer's scope (from `GET /users/positions`), plus "All". Matching ignores case. Shown only when staff are in the viewer's scope and the role filter is "All" or staff;
  - **status**: active (default), deactivated, or all.
- Each row or card shows avatar initials, name, `@telegram`, role/position badge, phone and status badges:
  - *Active* / *Deactivated*;
  - *Locked*;
  - *Password change pending*.
- Pagination, with 20 per page.
- **New user** button, shown with `users.create`.

**Create a user** (`users.create`)

- **Role:** limited to the roles the viewer may create. It defaults to the lowest one, usually staff.
- **Position (job title):** staff only, and required for them.
  - Free text, up to 50 characters, in any language. Examples: `Grill cook`, `Cashier`, `អ្នកដឹកជញ្ជូន`.
  - As you type, positions already used in your scope are suggested, which keeps spelling consistent.
  - Extra spaces are removed; case and Khmer text are kept as typed.
  - The hint says it's a **job title only**: position never changes what a user can see or do. Access comes only from role and permissions.
- **Other fields:** full name, Telegram username, optional phone, language.
- **Live login preview:** "Signs in as: sok_dara" shows how the username will be normalized.
- **Initial-password note:** the initial password is the Telegram username, and it must be changed at first sign-in.
- **After saving,** it opens the new user's page with a confirmation showing the initial password.

**Edit a user** (`users.update`)

- Same fields; the role is read-only. Staff can be given a new position at any time; it has no effect on their access.
- If the user is linked to Telegram and you change their username, a warning says the link will be removed.

## 9. User detail

**Path:** `/settings/users/<id>` (edit: `/settings/users/<id>/edit`, permissions tab: `?tab=permissions`).

- **Header:** name, `@telegram`, role/position badge, status badges.
- **Actions**, each shown only with the matching permission. All destructive actions ask for confirmation in a dialog.

  | Action | Permission |
  |---|---|
  | **Edit** | `users.update` |
  | **Reset password** | `users.reset_password` (superadmin and general manager only) |
  | **Deactivate** / **Reactivate** | `users.delete` |

  - Reset password sets the password back to the Telegram username. The dialog explains the user will be signed out everywhere and must choose a new password.
  - Deactivate / Reactivate is a soft on/off switch. A deactivated user is signed out immediately.

- **Details tab:**
  - full name, Telegram username and whether it's **linked** to a Telegram account;
  - role, position (shown exactly as entered, never translated), phone, language;
  - created, updated and deactivated dates;
  - locked-until time, if the account is locked.
- **Permissions tab:** see §10.
- Success and error messages are shown inline and are translated.

## 10. Permissions tab

Controls which features a user can access.

**Layout**

- Permissions are **grouped by module**, for example *User management / គ្រប់គ្រងអ្នកប្រើប្រាស់*.
- Each permission shows its localized name, description and code.
- Only permissions that can be assigned to the user's role are listed.
  - Staff have none in Phase 1, so an empty-state message is shown.

**Editing**

- Each permission has a checkbox. It is **editable only** when all of these hold:
  - you hold *Grant permissions*;
  - the user is in your scope;
  - you hold that permission yourself.
- Everything else is shown **read-only**, with a tooltip and an explanatory notice.
- Clicking a checkbox grants or revokes the permission immediately, with a small spinner on that row.
- Errors from the server are translated. Example: "You can only grant or revoke permissions you hold yourself".

## 11. Audit log

**Path:** `/settings/audit-logs`. **Who can open it:** the superadmin and the general manager.

- A chronological list of security events:
  - sign-ins and failed sign-ins;
  - lockouts;
  - password changes and resets;
  - user creation, edits, deactivation and reactivation;
  - permission grants and revokes;
  - profile updates.
- **Filter** by action type.
- Each entry shows:
  - the time, in the current language's format;
  - the action, as a translated badge, red for failures and locks;
  - **By** (actor) and **User** (target), linking to the user;
  - details: the permission code, or an expandable JSON view.
- **Revocations are highlighted.** When a revoked permission had been passed on to others by that user, an amber warning lists who still holds it, so managers can follow up (revoking does not cascade).
- Pagination, with 50 per page.

## 12. My profile

**Path:** `/settings/profile` (also from the avatar menu). Available to every user, including staff.

**Personal information**

- Edit your full name, phone and language.
- Saving the language switches the whole UI.

**Account**

- Shows your role and Telegram username, and whether Telegram is linked.

**Change password**

- Current password, new password and confirmation, with the same rules as §3.

**Reset my password** (superadmin and general manager only)

- Returns your password to its default and signs you out on all devices.
  - General manager: your Telegram username. You must change it at next sign-in.
  - Superadmin: `superadmin`.
- After confirming, you're taken to the login page with a message telling you which password to use.

## 13. Language (Khmer / English)

- **Khmer is the default.** English is fully supported: every label, message, role, audit action and error. Positions are free text and are shown as entered.
- **Switching** from the header takes effect instantly.
  - **Signed in:** the choice is saved to your profile and follows you to other devices.
  - **Signed out, or password change pending:** it is remembered on this device.
- **Your saved language is applied** automatically after sign-in.
- **Permission and module names** come from the server in both languages.
- **Errors are translated too,** including messages coming from the server. Example: *"ឈ្មោះអ្នកប្រើ ឬពាក្យសម្ងាត់មិនត្រឹមត្រូវ។"* / *"Incorrect username or password."*
- **Typography:** the Kantumruy Pro font with Khmer-friendly line height.

## 14. Error and status screens

| Situation | What the user sees |
|---|---|
| Page not allowed | "No access" with a link home. |
| Unknown page | "Page not found". |
| Server unreachable while restoring a session | A network error message and **Try again**. The session is kept. |
| Session expired | Refreshed silently. If that fails, the user is sent back to login. |
| Account deactivated while signed in | Signed out on the next request. |
| Password reset by a manager while signed in | Redirected to the forced password change. |

## 15. Screen access matrix

| Screen | Superadmin | General manager | Supervisor | Staff |
|---|---|---|---|---|
| Home, Production, Settings hub | ✅ | ✅ | ✅ | ✅ |
| Settings → My profile | ✅ | ✅ | ✅ | ✅ |
| Settings → Users (list / detail) | ✅ all below | ✅ supervisors, staff | ✅ staff (default) | ❌ |
| Create user | ✅ GM, supervisor, staff | ✅ supervisor, staff | ✅ staff (default) | ❌ |
| Edit user | ✅ | ✅ | ✅ (default) | ❌ |
| Deactivate / reactivate | ✅ | ✅ | only if granted | ❌ |
| Reset others' password | ✅ | ✅ | ❌ never | ❌ |
| Reset own password | ✅ | ✅ | ❌ | ❌ |
| Edit permissions | ✅ | ✅ (what they hold) | only if granted | ❌ |
| Settings → Audit log | ✅ | ✅ | ❌ | ❌ |

"(default)" means granted by default when the account is created. A manager can change these grants.

This matrix depends **only on role and permissions**. A staff member's position (e.g. `Grill cook` or `អ្នកដឹកជញ្ជូន`) never changes it: two staff with the same grants see exactly the same menu and screens.
