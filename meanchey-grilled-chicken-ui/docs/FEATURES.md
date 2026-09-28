# UI Features — Phase 1

What the Mean Chey Grilled Chicken UI (មាន់អាំងមានជ័យ) offers today. One React app serves both the **PC dashboard** and the **Telegram Mini App**.

Phase 1 covers sign-in, user management and access control (feature access levels), plus the first production features: **Suppliers** and **Customers**.

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
- [10. Access tab and Permissions (advanced)](#10-access-tab-and-permissions-advanced)
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
- **The superadmin** uses the same app. Its extra screens (Permissions (advanced), detailed permission entries in the audit log) are shown only when signed in as the superadmin. Everyone else sees the superadmin only as **System** (ប្រព័ន្ធ), which is also its role label.

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
│   ├── Suppliers         suppliers.view    /production/suppliers
│   └── Customers         customers.view    /production/customers
└── Settings              everyone          /settings
    ├── Users             users.view        /settings/users
    ├── Audit log         superadmin, GM    /settings/audit-logs
    └── My profile        everyone          /settings/profile
```

- **Each item appears only when the user is allowed to open it.** The rules are unchanged from before: Users needs `users.view`, and Audit log is for the superadmin and general manager.
- **Settings is always shown,** because everyone can open My profile.
- **Production is always shown,** even when none of its pages are visible, so its hub can explain that nothing is available yet.
- **Staff** see Home, Production and Settings. Production shows the "no access yet" message and Settings only My profile, which follows from the permissions with no special handling. Once the general manager sets e.g. Suppliers to *View only* on the Access tab, Suppliers appears for that staff member.
- **Desktop sidebar:** Home, Production and Settings.
  - While you're anywhere under Production or Settings, that section's visible sub-pages are listed indented below it.
  - The current page and its section are highlighted.
- **Mobile / Telegram bottom bar:** exactly three buttons, Home · Production · Settings. Settings stays highlighted on every Settings page.
- **Back buttons,** both in-page and Telegram's native one, go to the **parent screen**, not the browser history. For example: user details → Users → Settings → Home, and Suppliers → Production → Home. A deep link opened straight into the Mini App therefore still has a sensible way back.
- **Header:** language switcher (ខ្មែរ / EN) and an avatar menu.
- **Avatar menu:** name, role, Telegram username, **My profile** and **Log out**.
- **Permission changes show up quickly.** Menus refresh when Home, Production or Settings is opened and the cached permissions are more than a minute old. They also refresh whenever the server answers "no permission", "wrong role" or "out of scope".
- **Old links keep working.** Old addresses (`/users/…`, `/audit-logs`, `/profile`) redirect to their new place under `/settings`, keeping the rest of the address, for example `/users/<id>?tab=permissions`.

## 5. Home

- A welcome banner with the user's name and role badge (plus position for staff).
- Two large tiles, each with an icon, a title and a one-line description. They sit side by side on desktop and stack on mobile:
  - **Production:** day-to-day production and operations;
  - **Settings:** users, permissions and your account.

## 6. Production

**Path:** `/production`. **Who can open it:** everyone.

A hub with one card per Production page the user may open, built from the same menu definition as the sidebar:

| Card | Shown to |
|---|---|
| Suppliers | holders of `suppliers.view` |
| Customers | holders of `customers.view` |

With no visible cards (staff by default) it shows *"You don't have access to any production features yet"* with a hint to ask a manager.

### 6.1 Suppliers and customers

**Paths:** `/production/suppliers`, `/production/customers`. **Who can open them:** users whose Suppliers / Customers access is *View only* or *Full access* (§10): by default the general manager and supervisors; staff once the general manager turns it on. Both pages work the same way.

Top to bottom:

1. **Header:** title, total, and **New supplier** / **New customer** (with `*.create`).
2. **Figures (KPI cards):** **Active**, **New this month** and **Deactivated**.
   - Three in a row on desktop; a swipeable row on mobile. Grey placeholders while loading.
   - Tapping **Active** or **Deactivated** filters the list; the selected card is outlined.
   - "This month" follows the calendar month in Cambodia time.
3. **Search and filters:** a search box (name, location or phone; `345 678` finds `012 345 678`), a status filter (Active · Deactivated · All) and a sort (Name A–Z, Name Z–A, Newest, Oldest).
   - Filters are kept in the address (`?q=…&status=…&sort=…&page=…`), so Back and shared links keep them.
4. **List,** 20 per page:
   - **Desktop:** a table with Name, Location, Phone, Added, Status and a **⋮** menu.
   - **Mobile / Mini App:** cards with name, location and phone, a large green **Call** button (opens the phone dialer) and a **⋮** menu.
   - Phones are shown formatted (`012 345 678`, `+855 12 345 678`) and are tap-to-call on desktop too.
   - Deactivated records are dimmed with a *Deactivated* badge.
   - The **⋮** menu offers **Edit** (`*.update`) and **Deactivate** / **Reactivate** (`*.delete`); without either permission there is no menu.
5. **Empty states:** *No suppliers yet* (with the create button when allowed); *Nothing matches your search* with **Clear filters**; or, when only deactivated records exist, **Show deactivated**.

**Add / edit** opens a panel: a side drawer on desktop, a bottom sheet on mobile.

- Fields: **Name** (required, up to 150 characters), **Location** (optional, up to 255), **Phone** (optional, numeric keypad).
- Checked before sending, with the server's rules: name required, lengths, phone 8–15 digits (spaces, dashes, dots, brackets and a leading `+` are fine).
- Server errors appear under the field they concern, e.g. *"This phone number is already in use"* under Phone. A phone number can belong to only one **active** supplier (and one active customer).
- On success the panel closes, a confirmation appears above the list, and the list and figures refresh.

**Deactivate / reactivate** asks for confirmation first. Deactivated records keep their history and can be reactivated; reactivation fails if another active record now has the same phone.

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

- Same fields; the role isn't edited here (see **Change role** on the user's page, §9). Staff can be given a new position at any time; it has no effect on their access.
- If the user is linked to Telegram and you change their username, a warning says the link will be removed.

## 9. User detail

**Path:** `/settings/users/<id>` (edit: `/settings/users/<id>/edit`, tabs: `?tab=access`, `?tab=permissions`).

- **Header:** name, `@telegram`, role/position badge, status badges.
- **Actions**, each shown only with the matching permission. All destructive actions ask for confirmation in a dialog.

  | Action | Permission |
  |---|---|
  | **Edit** | `users.update` |
  | **Reset password** | `users.reset_password` (general manager) |
  | **Change role** | general manager (staff ↔ supervisor) and superadmin (general manager / supervisor / staff) |
  | **Deactivate** / **Reactivate** | `users.delete` (general manager; supervisors never) |

  - Reset password sets the password back to the Telegram username. The dialog explains the user will be signed out everywhere and must choose a new password.
  - Deactivate / Reactivate is a soft on/off switch. A deactivated user is signed out immediately.
  - **Change role** opens a panel (drawer on PC, bottom sheet on phones) listing the roles you can move this user to. Choosing *Staff* asks for a position (with suggestions). A note explains that access is reset to the new role's defaults, adjustable afterwards on the Access tab. Only one active general manager is allowed; otherwise a translated error is shown. The user stays signed in; their menus update at the next refresh.

- **Details tab:**
  - full name, Telegram username and whether it's **linked** to a Telegram account;
  - role, position (shown exactly as entered, never translated), phone, language;
  - created, updated and deactivated dates;
  - locked-until time, if the account is locked.
- **Tabs**, by viewer (§10):

  | Viewer | Details | Access | Permissions (advanced) |
  |---|---|---|---|
  | General manager (supervisor / staff) | ✅ | ✅ | — |
  | Supervisor (staff) | ✅ | — | — |
  | Superadmin | ✅ | ✅ | ✅ |

  A `?tab=` the viewer can't open falls back to Details.
- Success and error messages are shown inline and are translated.

## 10. Access tab and Permissions (advanced)

### Access tab (ការចូលប្រើ)

How the general manager decides what supervisors and staff can use. Shown when the viewer may manage access (*can manage features*) and at least one feature applies to the user. The general manager can set **any level of any feature** available to that user's role; nothing here depends on the general manager's own permissions.

- **Grouped by menu:** **Production** (Suppliers, Customers), then **Settings** (Staff management, supervisors only).
- Each row: the feature's name and a one-line description (from the server, in the current language), and a segmented control **Off · View only · Full access** (*បិទ · មើលតែប៉ុណ្ណោះ · ពេញលេញ*).
- A legend at the top: *View only* = can see the list; *Full access* = can add, edit and deactivate. For Staff management, Full access means add and edit staff: supervisors never deactivate people.
- **Each click saves** immediately, with a spinner on that row. On error the previous level comes back and a translated message is shown.
- From *Off*, *View only* has a dashed outline as the suggested next step; it still takes a click.
- **Custom:** if a user's permissions match no level (only possible through the superadmin's detailed permissions), a neutral *Custom* badge is shown and no level is selected. Picking a level replaces it.
- Rows are disabled only when the user is deactivated. No explanation mentions other roles.
- Defaults: supervisors start with everything at **Full access**, staff with everything **Off**.
- Changes take effect on the user's next menu refresh (within a minute, or at once on their next "no permission" answer). If you change your own access, your menus refresh immediately.
- On phones and in the Mini App the control sits under the name, full width, with large touch targets.

### Permissions (advanced), superadmin only

Only for the superadmin. Shows the detailed permissions under the feature levels: grouped by module, each with its localized name, description and code, a checkbox, and a lock reason from the server when it can't be changed (e.g. the user is deactivated). Clicking a checkbox grants or revokes that one permission immediately. General-manager-only permissions (deactivate users, reset passwords, manage access) are managed here.

Supervisors and staff never see any permission or access information.

## 11. Audit log

**Path:** `/settings/audit-logs`. **Who can open it:** the general manager and the superadmin. The general manager doesn't see entries made by the superadmin (nor detailed permission changes).

- A chronological list of security events:
  - sign-ins and failed sign-ins;
  - lockouts;
  - password changes and resets;
  - user creation, edits, role changes (e.g. *"Staff → Supervisor"*), deactivation and reactivation;
  - access changes (*Changed access*), shown as e.g. *"Suppliers: View only → Full access"*;
  - detailed permission grants and revokes, including automatic ones on deploy: **superadmin only** (the general manager sees access changes instead);
  - profile updates;
  - suppliers and customers added, edited, deactivated and reactivated.
- **Filters:** record type (All · Suppliers · Customers) and action type.
- Each entry shows:
  - the time, in the current language's format;
  - the action, as a translated badge, red for failures and locks;
  - **By** (actor) and **User** (target), linking to the user. Actions by the system show **System** (ប្រព័ន្ធ), without a link;
  - for supplier / customer entries, the **record**: its type and current name, linking to the Suppliers / Customers page with that name already searched (including deactivated records);
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
- No permission or access information is shown, for any role.

**Change password**

- Current password, new password and confirmation, with the same rules as §3.

**Reset my password** (general manager)

- Returns your password to your Telegram username and signs you out on all devices. You must change it at next sign-in. (The superadmin's reset returns it to its initial password instead.)
- After confirming, you're taken to the login page with a message telling you which password to use.

## 13. Language (Khmer / English)

- **Khmer is the default.** English is fully supported: every label, message, role, audit action and error, including the supplier / customer pages and their figures. Positions are free text and are shown as entered.
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
| Settings → Users (list / detail) | ✅ all below | ✅ supervisors, staff | Staff management ≥ View only (default Full): staff | ❌ |
| Create / edit user | ✅ | ✅ | Staff management = Full (default) | ❌ |
| Change role (promote / demote) | ✅ GM ↔ supervisor ↔ staff | ✅ supervisor ↔ staff | ❌ | ❌ |
| Deactivate / reactivate users | ✅ | ✅ | ❌ never | ❌ |
| Reset others' password | ✅ | ✅ | ❌ never | ❌ |
| Reset own password | ✅ | ✅ | ❌ | ❌ |
| User detail → Access tab | ✅ | ✅ (supervisors, staff) | ❌ | ❌ |
| User detail → Permissions (advanced) | ✅ | ❌ | ❌ | ❌ |
| Settings → Audit log | ✅ everything | ✅ without detailed permission entries | ❌ | ❌ |
| Production → Suppliers (list, figures) | ✅ | ✅ | Suppliers ≥ View only (default Full) | Suppliers ≥ View only (default Off) |
| Add / edit / deactivate suppliers | ✅ | ✅ | Suppliers = Full (default) | Suppliers = Full |
| Production → Customers (list, figures) | ✅ | ✅ | Customers ≥ View only (default Full) | Customers ≥ View only (default Off) |
| Add / edit / deactivate customers | ✅ | ✅ | Customers = Full (default) | Customers = Full |

"Suppliers = Full" etc. refers to the levels the general manager sets on the Access tab (§10). "(default)" is the level a new account starts with.

This matrix depends **only on role and access levels**. A staff member's position (e.g. `Grill cook` or `អ្នកដឹកជញ្ជូន`) never changes it: two staff with the same levels see exactly the same menu and screens.
