# UI Architecture

How the Mean Chey Grilled Chicken UI is built. For what it *does*, see [FEATURES.md](FEATURES.md). For the backend, see `../meanchey-grilled-chicken-api/docs/ARCHITECTURE.md`.

- [1. Overview](#1-overview)
- [2. Tech stack](#2-tech-stack)
- [3. Source layout](#3-source-layout)
- [4. Boot sequence](#4-boot-sequence)
- [5. Session and auth state](#5-session-and-auth-state)
- [6. API client and token refresh](#6-api-client-and-token-refresh)
- [7. Routing and guards](#7-routing-and-guards)
- [8. Permission-driven UI](#8-permission-driven-ui)
- [9. Layouts and Telegram integration](#9-layouts-and-telegram-integration)
- [10. Server state (TanStack Query)](#10-server-state-tanstack-query)
- [11. Internationalization](#11-internationalization)
- [12. Error handling](#12-error-handling)
- [13. Styling and components](#13-styling-and-components)
- [14. Build, dev server and deployment](#14-build-dev-server-and-deployment)
- [15. Extending the UI](#15-extending-the-ui)
- [16. Design decisions](#16-design-decisions)

---

## 1. Overview

```mermaid
flowchart LR
    subgraph Browser["Browser / Telegram WebView"]
        TGJS[telegram-web-app.js<br/>window.Telegram.WebApp]
        subgraph SPA[React SPA]
            AUTH[AuthProvider]
            ROUTER[React Router + guards]
            PAGES[Pages]
            RQ[TanStack Query cache]
            AX[axios client<br/>+ refresh interceptor]
        end
    end
    VITE[Vite dev server<br/>proxy /api]
    API[FastAPI /api/v1]

    TGJS --> AUTH
    AUTH --> RQ
    ROUTER --> PAGES
    PAGES --> RQ
    RQ --> AX
    AX --> VITE --> API
```

It is a single-page app with no server-side rendering. All data comes from the API. The app holds no business rules beyond UX hints.

## 2. Tech stack

| Concern | Choice |
|---|---|
| Build | Vite 6, TypeScript (strict) |
| UI | React 18 |
| Styling | Tailwind CSS 3; `brand` = Tailwind orange; font Kantumruy Pro (Google Fonts) |
| Routing | React Router 6 (`createBrowserRouter`) |
| Server state | TanStack Query 5 |
| HTTP | axios, with interceptors |
| i18n | i18next + react-i18next (`km` default, `en`) |
| Telegram | Official `telegram-web-app.js` script |

## 3. Source layout

```
src/
├── main.tsx               # initTelegram, QueryClient, AuthProvider, RouterProvider
├── router.tsx             # route tree + guards
├── index.css              # Tailwind + base styles
├── auth/
│   ├── AuthProvider.tsx   # session state machine, login/logout, Telegram auto-login, me query
│   ├── usePermission.ts   # usePermission, useHasRole, useCanAccess
│   ├── Can.tsx            # <Can permission|roles>
│   └── guards.tsx         # RequireAuth, PublicOnly, RequireAccess
├── lib/
│   ├── api.ts             # axios instance, token injection, refresh + session events
│   ├── storage.ts         # safe localStorage + tokenStore
│   ├── errors.ts          # getError, useErrorMessage, ClientError
│   ├── format.ts          # dates, localized names, initials, username normalize
│   ├── telegram.ts        # telegram handle, isTelegramMiniApp, initTelegram
│   ├── paths.ts           # app routes (paths.users, paths.user(id)…), legacy prefixes, parentPath, isUnder
│   ├── roles.ts           # isSuperadmin, AUDIT_ROLES, SUPERADMIN_LOGIN: superadmin checks in one place
│   ├── types.ts           # API types (mirror of the API schemas)
│   ├── usePositions.ts    # ['user-positions'] query
│   └── useDebounced.ts
├── i18n/                  # i18next init + locales/{km,en}.json
├── layouts/               # AppShell → DesktopLayout | MobileLayout, nav.ts (menu tree), Brand
├── components/            # ui.tsx kit, Sheet, ActionMenu, SegmentedControl, icons, badges, NavTile, LanguageSwitcher, ProfileMenu,
│                          #   ChangePasswordForm
├── pages/
│   ├── HomePage.tsx, LoginPage.tsx, ChangePasswordPage.tsx, StatusPages.tsx, AuthLayout.tsx
│   ├── production/        # ProductionPage (hub) + partners/ (generic Suppliers/Customers list: config,
│   │                      #   PartnerListPage, KpiCards, PartnerFormSheet, validation)
│   └── settings/          # SettingsPage (hub), AuditLogPage, ProfilePage, users/* (incl. UserAccessTab, UserPermissionsTab, RoleChangeSheet)
└── types/telegram.d.ts    # minimal Telegram.WebApp typings
```

**Dependency direction:**

```
pages → components, auth, lib → (nothing app-specific)
```

`lib/` never imports React components. `auth/` is the only layer that talks to the session.

## 4. Boot sequence

```mermaid
sequenceDiagram
    participant HTML as index.html
    participant M as main.tsx
    participant A as AuthProvider
    participant API

    HTML->>HTML: load telegram-web-app.js (sync)
    HTML->>M: load module
    M->>M: initTelegram() → ready(), expand(), header colors
    M->>M: i18n init (saved language or km)
    M->>A: render
    alt tokens in storage
        A->>API: GET /auth/me
        API-->>A: Me → status = authenticated, apply user.language
    else in Telegram, no tokens
        A->>API: POST /auth/telegram {initData}
        API-->>A: tokens → store → GET /auth/me
    else
        A-->>A: status = anonymous → /login
    end
```

## 5. Session and auth state

`AuthProvider` exposes this context:

```ts
{
  status,               // 'booting' | 'anonymous' | 'authenticated' | 'offline'
  me,                   // Me | null
  telegramError,        // code from the auto-login, if it failed
  login, loginWithTelegram, logout, refreshMe,
}
```

```mermaid
stateDiagram-v2
    [*] --> booting
    booting --> authenticated: /auth/me ok
    booting --> anonymous: no token / auth error
    booting --> offline: network error
    offline --> booting: retry
    anonymous --> booting: login / Telegram login
    authenticated --> anonymous: logout / refresh failed / ACCOUNT_DISABLED
```

- **`me` is a TanStack Query** (`['me']`), enabled when an access token exists. The context doesn't copy it; it derives state from the query.
- **Tokens** live in `tokenStore` (`localStorage`, falling back to memory).
- **Login** does three things:
  1. stores the tokens;
  2. clears every cached query, so no data from a previous user leaks into the new session;
  3. flips `hasToken`, which triggers the `me` fetch.
- **Logout** calls `/auth/logout` (best effort), then clears the tokens and the query cache.
- **Offline handling.** A network error on `/auth/me` keeps the tokens and shows *offline* with a retry, instead of logging the user out. Any other error ends the session.
- **Language:**
  - after `me` loads, the user's saved language is applied once per `(user, language)` pair;
  - a later language change made locally, for example while a password change is pending, is not overwritten by refetches.

## 6. API client and token refresh

`lib/api.ts` creates the axios instance at `VITE_API_BASE_URL` (default `/api/v1`).

```mermaid
sequenceDiagram
    participant Q1 as request A
    participant Q2 as request B
    participant I as interceptor
    participant API

    Q1->>API: GET /users (expired)
    Q2->>API: GET /permissions (expired)
    API-->>I: 401 TOKEN_EXPIRED (A)
    I->>API: POST /auth/refresh  (single-flight promise)
    API-->>I: 401 TOKEN_EXPIRED (B) → awaits same promise
    API-->>I: new tokens
    I->>API: retry A, retry B
```

- **Request interceptor:** adds `Authorization: Bearer <access>`.
- **Response interceptor:**
  - **`401` with `TOKEN_EXPIRED` or `INVALID_TOKEN`:** refresh once and retry.
    - Applies only if a refresh token exists and the request wasn't `/auth/login`, `/auth/telegram` or `/auth/refresh`.
    - Concurrent 401s share **one** refresh promise.
    - The refresh call uses bare `axios`, not the instance, so it can't recurse.
  - **Refresh failure, or `401 ACCOUNT_DISABLED`:** clear the tokens and dispatch `auth:logout`.
  - **`403` with `PASSWORD_CHANGE_REQUIRED`, `MISSING_PERMISSION`, `FORBIDDEN_ROLE` or `FORBIDDEN_SCOPE`:** dispatch `auth:refresh-me`, because the cached `/auth/me` is probably stale. `AuthProvider` refetches it. The guards and menus then redirect to the password change, or drop items the user lost.
- **Window events** decouple the interceptor from React: `AuthProvider` listens and updates state.

## 7. Routing and guards

```
/login                               PublicOnly
<RequireAuth>
  /change-password                   (standalone, AuthLayout)
  <AppShell>
    /                                Home (Production + Settings tiles)
    /production
      index                          ProductionPage (hub: cards from the nav tree, or "no access yet")
      suppliers                      RequireAccess suppliers.view → PartnerListPage(SUPPLIERS)
      customers                      RequireAccess customers.view → PartnerListPage(CUSTOMERS)
    /settings
      index                          SettingsPage (hub: cards from the nav tree)
      users                          RequireAccess users.view
        index                        UsersList
        new                          RequireAccess users.create → UserForm(create)
        :id                          UserDetail (?tab=permissions)
        :id/edit                     RequireAccess users.update → UserForm(edit)
      audit-logs                     RequireAccess roles=AUDIT_ROLES (superadmin, general manager)
      profile                        Profile
    /users, /users/*                 LegacyRedirect → /settings/users…
    /audit-logs, /audit-logs/*       LegacyRedirect → /settings/audit-logs…
    /profile, /profile/*             LegacyRedirect → /settings/profile…
    *                                NotFound
```

**Paths.** Every frontend URL comes from `lib/paths.ts` (`paths.users`, `paths.user(id)`, `paths.editUser(id)`, `paths.suppliers`, `paths.customers`, …). Components never write route literals, so moving a page is a one-file change. API URLs such as `api.get('/users')` are unrelated and stay literal.

**Legacy redirects.** `LegacyRedirect` swaps the old prefix (from `LEGACY_PREFIXES`) for the new one and keeps the rest of the path, the query string and the hash, e.g. `/users/<id>/edit?x=1#a` → `/settings/users/<id>/edit?x=1#a`.

- It sits inside `RequireAuth`. An old deep link opened while signed out goes through login, `location.state.from` keeps the old path, and after sign-in the redirect sends the user to the new place.
- The redirect routes can be deleted once no old links are in circulation.

| Guard | Behavior |
|---|---|
| `RequireAuth` | See the list below. |
| `PublicOnly` | For `/login`. Sends signed-in users to their original destination (`location.state.from`) or to `/`. |
| `RequireAccess` | Takes `permission` and/or `roles`. Renders `ForbiddenPage` if denied. Works as a layout route (`<Outlet/>`) or as a wrapper around children. |

The two `PartnerListPage` routes get distinct React `key`s, so switching between Suppliers and Customers remounts the page instead of carrying state (search text, open panel) across.

`RequireAuth` in detail:

- **booting** → spinner.
- **offline** → retry screen.
- **anonymous:**
  - if a Telegram auto-login failed → the Telegram error screen;
  - otherwise → `/login`, remembering where the user was going.
- **password change pending** → only `/change-password` is allowed.
- **`/change-password` without a pending change** → redirected to `/`.

## 8. Permission-driven UI

All checks read `me.permissions` and `me.user.role` from `/auth/me`:

```ts
usePermission('users.create')                    // boolean
useHasRole('superadmin', 'general_manager')      // boolean
useCanAccess()({ permission, roles })            // shared by <Can>, RequireAccess, nav
<Can permission="users.delete" fallback={…}>…</Can>
```

- **Menu tree.** `layouts/nav.ts` declares `NAV_ITEMS` as a tree:

  ```ts
  { to, labelKey, descriptionKey?, icon, permission?, roles?, end?, keepWhenEmpty?, children? }
  ```

  - **Top level:** Home, Production, Settings.
  - **Production's `children`:** Suppliers (`suppliers.view`, icon `truck`) and Customers (`customers.view`, icon `store`).
  - **Settings' `children`:** Users (`users.view`), Audit log (roles `superadmin`, `general_manager`) and My profile. These carry the same rules as before.
- **`useNavItems()`** returns the visible top-level items, each with only its visible children.
  - A section whose children are **all** filtered out is hidden, unless it has `keepWhenEmpty`.
  - **Production is `keepWhenEmpty`**: staff without partner permissions still get the Production tab, and its hub explains that nothing is available yet.
  - A section declared with `children: []` is a real but empty section and also stays visible.
  - `useNavChildren(to)` returns one section's visible children.
- **Consumers,** all reading the same tree:
  - the desktop sidebar: top level plus the nested children of the current section;
  - the mobile bottom nav: top level only;
  - the Home tiles: top-level sections, via `NavTile`;
  - the Production and Settings hubs: `useNavChildren(paths.production | paths.settings)`, via `NavTile`.
- **Staff** see only My profile under Settings purely because of these rules. There is no role-specific UI code.
- **Freshness.** Home and the Production and Settings hubs call `useRefreshMeWhenStale()`, which adds a `['me']` observer that refetches if the cached copy is more than 60 s old. Combined with the 403 → `auth:refresh-me` rule (§6), a revoked permission disappears from the menus without a reload.
- **Per-object decisions come from the API.**
  - **Access tab** (`UserAccessTab`): shown when `me.can_manage_features` and `GET /users/{id}/features` returns at least one menu. The server decides which features apply (`applies_to`), the current level (`off` / `view` / `full` / `custom`) and `can_edit`; the client only renders them. Each segment click `PUT`s the level optimistically (rolled back on error) and invalidates `['user-features', id]`, plus `['me']` when editing oneself.
  - **Permissions (advanced)** (`UserPermissionsTab`, superadmin only) uses `can_edit` / `reason` from `GET /users/{id}/permissions`; `reason` is translated through `errors.<CODE>`.
  - `UserDetailPage` builds the tab list from these rules; an unknown or unavailable `?tab=` falls back to Details.
  - The Create User form offers `me.manageable_roles`; **Change role** offers the manageable roles other than the user's current one, and is shown only with `users.update` when there is at least one (so never to supervisors).
- **Security boundary:** the API. UI checks only avoid showing dead-end actions.
- **System references.** Every user reference from the API is a `UserRef` with `is_system`; render `is_system` (or a null `id`) as "System" without a link. The API uses it for actions by the system and to hide the superadmin from everyone else.
- **The superadmin in the UI.** Superadmin checks go through `lib/roles.ts` (`isSuperadmin`, `AUDIT_ROLES`, `SUPERADMIN_LOGIN`). Its role label (`roles.superadmin`) is "System" / "ប្រព័ន្ធ", the same word the API uses when it hides the superadmin from others. The code is a single bundle; the superadmin-only screens are ordinary runtime checks.

## 9. Layouts and Telegram integration

- **Layout choice:** `AppShell` picks `MobileLayout` when `isTelegramMiniApp || matchMedia('(max-width: 767px)')`, and `DesktopLayout` otherwise.
- **Desktop:** a sticky 256 px sidebar and a top bar with `LanguageSwitcher` and `ProfileMenu`.
  - The sidebar lists the top-level items.
  - When the route is under a section (`isUnder(pathname, '/production')`, `'/settings'`), that section's visible children appear indented below it.
  - The section's own page (`/settings`) is filled; on a child page, the parent keeps the brand color and only the child is filled.
- **Mobile:** a sticky top bar and a fixed bottom nav with exactly the top-level items (Home · Production · Settings). It uses `env(safe-area-inset-bottom)` padding, and the main content reserves space for the nav.
  - The Settings tab is a non-`end` `NavLink`, so it stays active on every `/settings/*` route.
- **Telegram helpers** (`lib/telegram.ts`):
  - `isTelegramMiniApp = Boolean(Telegram.WebApp.initData)`. The script also loads in normal browsers, so the presence of `initData` is the real signal.
  - `initTelegram()` calls `ready()` and `expand()` and sets the header and background colors to match the brand.
  - `MobileLayout` wires Telegram's **BackButton**: hidden on `/`, shown elsewhere.
    - On click it navigates to `parentPath(pathname)`, i.e. the path with its last segment dropped: `/settings/users/:id/edit` → `/settings/users/:id` → `/settings/users` → `/settings` → `/`, and `/production/suppliers` → `/production` → `/`.
    - It uses the route tree, not history (`navigate(-1)`), so a deep link opened directly in the Mini App still goes somewhere sensible.
    - In-page `PageHeader` back buttons follow the same parent targets.
- **Auth pages** (login, change password, Telegram error, offline) use `AuthLayout`: a centered card with the brand and language switcher.

## 10. Server state (TanStack Query)

| Query key | Source |
|---|---|
| `['me']` | `GET /auth/me` (staleTime 60 s) |
| `['users', params]` | `GET /users` (`keepPreviousData` for smooth paging and filtering) |
| `['user', id]` | `GET /users/{id}` |
| `['user-permissions', id]` | `GET /users/{id}/permissions` (superadmin only) |
| `['user-features', id]` | `GET /users/{id}/features` (enabled with `me.can_manage_features`) |
| `['user-positions']` | `GET /users/positions`, via `usePositions()` in `lib/usePositions.ts`. Enabled with `users.view`, staleTime 60 s. Feeds the position `<datalist>` suggestions in the user form and the position filter on the users list. |
| `['audit-logs', params]` | `GET /audit-logs` |
| `['suppliers', params]` / `['customers', params]` | `GET /suppliers` / `GET /customers` (`keepPreviousData`; the previous page stays visible, dimmed, while the next loads) |
| `['suppliers-stats']` / `['customers-stats']` | `GET /suppliers/stats` / `GET /customers/stats` (KPI cards) |
| `['supplier', id]` / `['customer', id]` | Single record; written with `setQueryData` from mutation responses |

- Mutations use `useMutation`. After a change they either write the response straight into the cache (`setQueryData`, e.g. after editing a user or the profile) or invalidate the affected keys: `users`, `user`, `user-permissions`. Creating or editing a user also invalidates `user-positions`, so a newly typed position shows up in the suggestions and filter. A role change (`RoleChangeSheet`, `POST /users/{id}/role`) writes the returned user into `['user', id]` and invalidates `users`, `user-features`, `user-permissions` and `user-positions`.
- Supplier / customer mutations (create, edit, deactivate, reactivate) write the returned record into `[entity, id]` and invalidate both the list prefix (`[resource]`) and the stats key, so the table and the KPI cards update together. The keys are built by `partnerKeys(config)`.
- Defaults: `retry: 1`, `refetchOnWindowFocus: false`. The Telegram WebView focuses and blurs often, so refetching on focus would be noisy.

## 11. Internationalization

- `i18n/index.ts` initializes i18next with the bundled `km.json` and `en.json`.
  - Initial language: the value saved in `localStorage` (`mc.language`), otherwise `km`.
  - `fallbackLng: en`.
  - On every change, `<html lang>` is updated and the choice is saved.
- `setLanguage(lang)` is the single entry point.
- `LanguageSwitcher` calls `setLanguage`. When signed in, and no password change is pending, it also calls `PATCH /me` and writes the result into the `['me']` cache.
- **Key conventions:**

  | Keys | Content |
  |---|---|
  | `roles.*`, `languages.*` | Enum labels. Positions are free text from the user record and are never translated. |
  | `errors.<API_CODE>` | One key per API error code, plus client codes (`PASSWORDS_DO_NOT_MATCH`, `NETWORK_ERROR`, `UNKNOWN`) |
  | `audit.actions.<action with . replaced by _>` | Audit action labels (including `supplier_*`, `customer_*`) |
  | `partners.*` | Shared supplier/customer texts: field labels and hints, KPI labels, status and sort options, list actions |
  | `suppliers.*`, `customers.*` | Per-list texts: title, description, buttons, empty states, confirmations, success messages (`{{name}}`) |

- **Server-provided bilingual text** (permission and module names and descriptions) goes through `useLocalized()`, which picks `*_km` or `*_en` with an English fallback.
- **Dates** use `Intl.DateTimeFormat` with the `km-KH` or `en-GB` locale, via `useFormatDate()`.
- **Key parity:** `npm run check:i18n` fails the build step if the two locale files have different keys.
- Access tab strings live under `access.*` (level labels, legend, menus, feature names for the audit log); feature names and descriptions on the tab itself come from the API (`useLocalized`).

## 12. Error handling

```ts
getError(err) → { code, details }
// ClientError        → its own code
// axios, no response → NETWORK_ERROR
// axios, API body    → error.code / error.details
// otherwise          → UNKNOWN

useErrorMessage()(err) → t(`errors.${code}`, { ...details, time, min })
```

- Details are turned into readable interpolation values. For example, `locked_until` becomes a localized `time`.
- Forms keep the raw error and translate it at render time, so switching language re-translates an error that is already on screen.
- **Client-side validation** throws `ClientError` with the same codes the server uses, for example `PASSWORD_TOO_SHORT` or `INVALID_PHONE` (with the same `min_digits` / `max_digits` details), so messages are identical whichever side caught the problem. Where the server only says `VALIDATION_ERROR`, the client uses field-specific codes (`NAME_REQUIRED`, `FIELD_TOO_LONG`).
- **Field-level server errors.** The partner form maps an error to its field: `DUPLICATE_PHONE` / `INVALID_PHONE` → phone; `VALIDATION_ERROR` → the field in `details.fields[].loc`; anything else → an alert above the form.

## 13. Styling and components

- **Tailwind utility classes only,** with no CSS modules. `cx()` joins class names.
- **`components/ui.tsx`** is a small in-house kit:
  - `Button` (primary / secondary / danger / ghost, loading state);
  - form controls: `Input`, `Select`, and `Field`, which generates the id and renders the label and hint;
  - containers and feedback: `Card`, `Badge`, `Alert`, `Spinner`, `EmptyState`;
  - page structure: `PageHeader` (optional back button), and `ConfirmDialog` (bottom sheet on mobile, centered on desktop, Escape to close);
  - `useEscapeKey(open, onClose)`, shared by the dialogs.
- **`components/Sheet.tsx`** extends the `ConfirmDialog` pattern for forms and longer content: a full-height **side drawer** on desktop and a **bottom sheet** (max 90 % height, grab handle, safe-area padding) on mobile, chosen with `useIsMobileLayout()`. It has a title bar with a close button, a scrollable body and an optional sticky footer. Escape and backdrop clicks close it unless `busy`, and page scrolling is locked while it's open. The footer's submit button targets the form with `form="<id>"`.
- **`components/SegmentedControl.tsx`:** a radio group of buttons (`role="radiogroup"`), full width on phones with 40 px touch targets. `value` may match no segment (the *Custom* state). `suggested` adds a dashed outline as a hint only.
- **`components/ActionMenu.tsx`:** a **⋮** button with a small menu of `{label, icon, tone, onSelect}` items. It uses fixed positioning, so it isn't clipped by tables or scroll containers, and it opens upwards near the bottom of the screen. It renders nothing when there are no items, so permission-filtered item lists need no extra check.
- **Icons:** inline SVG paths in `components/icons.tsx`, with no icon dependency.
- **`scrollbar-none`** (in `index.css`): horizontal scrollers such as the mobile KPI row swipe without a visible scrollbar.
- **Accessibility:**
  - labelled controls;
  - `role="alert"` on errors;
  - `aria-pressed` on the language toggle;
  - `aria-haspopup` and `aria-expanded` on the profile menu;
  - dialogs with `aria-modal`.

## 14. Build, dev server and deployment

| Command | Purpose |
|---|---|
| `npm run dev` | Vite on `:5173`, `host: true`, `allowedHosts: true` (for ngrok / cloudflared), proxies `/api` → `VITE_API_PROXY_TARGET`. That covers both `/api/v1` and the Telegram webhook `/api/telegram/webhook`, so one tunnel to `:5173` serves the Mini App, the API and the bot. |
| `npm run build` | `tsc --noEmit` then `vite build` → `dist/` |
| `npm run typecheck` | Types only |
| `npm run check:i18n` | Locale key parity |

**Production**

- Serve `dist/` as static files with an SPA fallback, so unknown paths return `index.html`.
- Preferably serve the API from the **same origin** under `/api`. That needs no CORS, and a single HTTPS domain serves the Mini App, the API and the Telegram webhook (`/api/telegram/webhook`). Make sure the reverse proxy forwards all of `/api/*`.
- Otherwise:
  1. build with `VITE_API_BASE_URL=https://api.example.com/api/v1`;
  2. add the UI origin to the API's `CORS_ORIGINS`.
- The Telegram Mini App URL must be **HTTPS**.

## 15. Extending the UI

For a new feature, for example `orders`, after its permissions exist in the API registry, first decide where it lives:

- **Under Production** (most business features), e.g. `/production/orders`;
- **Under Settings** (configuration and admin screens), e.g. `/settings/branches`;
- **A new top-level section**, only for a genuinely separate area. It gets its own sidebar and bottom-nav entry and Home tile, and the bottom bar gets tight beyond 4–5 items.

Then:

1. **Types:** add them to `lib/types.ts`.
2. **Path:** add it to `lib/paths.ts`, e.g. `orders: '/production/orders'`, `order: (id) => …`.
3. **Page:** create `pages/production/orders/…` (or `pages/settings/…`). Fetch data with `useQuery` using a feature-specific key, and give the page a `PageHeader` whose `back` is the parent path.
4. **Route:** nest it under `/production` (or `/settings`) in `router.tsx`, wrapped in `<RequireAccess permission="orders.view">`.
5. **Navigation:** add a child to the section's `children` in `NAV_ITEMS`, with `permission: 'orders.view'`, an icon, `labelKey` and `descriptionKey`. What follows from that:
   - It appears automatically in the sidebar (nested) and, for Settings, as a hub card.
   - It also appears on the Production or Settings hub page as a card.
   - For a **new top-level section**, add a top-level entry instead. It needs `children` if it has sub-pages, a hub page if it has children, and a `descriptionKey` for its Home tile.
6. **Actions:** wrap them in `<Can permission="orders.create">`.
7. **Strings:** add them to `km.json` **and** `en.json` (label, description, page texts, any new API error codes). Run `npm run check:i18n`.

The Access tab, the Permissions (advanced) tab and the Telegram back button need no changes. A feature added to the API's `FEATURES` registry appears on the Access tab automatically, in its menu group, with names from the API; only its audit label needs an `access.featureNames.<code>` translation. The back target follows the path structure.

**Pattern: generic list page.** Suppliers and Customers are one page, `pages/production/partners/PartnerListPage.tsx`, configured by a `PartnerConfig` (`config.ts`):

```ts
{ resource: 'suppliers', entity: 'supplier', path: paths.suppliers, icon: 'truck' }
```

- `resource` is the API path (`/suppliers`), the permission prefix (`suppliers.create`) and the i18n namespace (`suppliers.title`).
- `entity` is the single-record query key and the audit `entity_type`.
- `partnerKeys(config)` builds the query keys; `permission(config, action)` the permission codes; `partnerSearchLink(config, q)` the audit log's deep link.

The page brings the KPI cards, URL-driven filters (`?q&status&sort&page`), table/card list, `ActionMenu`, the `PartnerFormSheet` and confirm dialogs. Another list with the same fields needs a config, a route, a nav child and its `<resource>.*` translations.

## 16. Design decisions

| Decision | Rationale |
|---|---|
| One app for PC and Mini App | One codebase and one auth flow. Only the layout and sign-in entry point differ. |
| Tokens in `localStorage` | Works inside the Telegram WebView and across reloads. The short access-token lifetime and server-side refresh revocation limit the exposure. An httpOnly cookie setup is a future option if the UI and API share a domain. |
| `/auth/me` as the single source of the user's rights | Menus, guards and forms react to grants and revokes after a refetch, with no client copy of the rules. |
| `can_edit` computed by the server | Keeps the complex grant rules in one place (the API). |
| Window events between the interceptor and React | The interceptor stays framework-agnostic, and session changes flow through one owner (`AuthProvider`). |
| Error codes translated in the client | The API stays language-neutral, and every message, including errors, switches with the language. |
| No component library | Small bundle, full control over Khmer typography, and a consistent mobile/desktop look. |
| Khmer default, English fallback | Matches the primary audience. A missing Khmer string still shows readable English. |
| Two sections (Production, Settings) and a nav tree | Business work and administration are kept apart. The bottom bar stays at three items as features grow, and one tree drives the sidebar, bottom nav, Home tiles and Settings hub. |
| One generic list page for suppliers and customers | The two lists have identical fields and rules; one implementation keeps them from drifting and makes the next similar list cheap. |
| List filters in the URL | Links (e.g. from the audit log) can open a prefilled search, and Back or a refresh keeps the filters. |
| Lock reasons from the server (`reason`) | Explains a locked permission without duplicating the grant rules, including `grantable_by`, in the client. |
| Drawer on desktop, bottom sheet on mobile | Keeps the list visible beside the form on a PC, and is thumb-friendly in the Mini App. |
| Access tab with levels, detailed permissions superadmin-only | Managers pick Off / View only / Full access per feature instead of permission codes; the server owns the mapping, so the UI renders whatever features exist. |
| One bundle; the superadmin labelled "System" | A separate admin build was considered and dropped as too complex. The API is the boundary: it never returns superadmin data to anyone else, and the UI's own label for the role reads "System". The bundle still contains the superadmin-only screens' code. |
| Back = parent route, not history | Mini App sessions often start from a deep link with no history. The route structure always gives a meaningful "up". |
