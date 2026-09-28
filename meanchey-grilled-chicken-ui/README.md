# Mean Chey Grilled Chicken — UI (មាន់អាំងមានជ័យ)

One React app for two clients:

- the **PC dashboard**, with a sidebar layout;
- the **Telegram Mini App**, with a mobile layout and bottom navigation. The same mobile layout is used on narrow browser windows.

📄 Detailed docs: [docs/FEATURES.md](docs/FEATURES.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

Stack: Vite · React 18 · TypeScript · Tailwind CSS · React Router · TanStack Query · axios · react-i18next (Khmer default, English) · Kantumruy Pro font.

Phase 1 screens:

- Login, plus automatic login inside Telegram
- Forced password change
- Users list, create and edit
- User detail, with a Permissions tab
- Audit log (superadmin / GM only)
- My profile

## Setup

The API must be running; see `../meanchey-grilled-chicken-api/README.md`.

```bash
npm install
cp .env.example .env     # optional; the defaults work with the API on localhost:8000
npm run dev              # http://localhost:5173
```

Other scripts:

```bash
npm run build        # typecheck + production build (dist/)
npm run typecheck
npm run check:i18n   # km.json and en.json must have exactly the same keys
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `VITE_API_BASE_URL` | `/api/v1` | API base URL used by the browser. Keep the default to go through the dev proxy. |
| `VITE_API_PROXY_TARGET` | `http://localhost:8000` | Where the Vite dev server proxies `/api`. |

In production, serve `dist/` as a static SPA: every unknown path must fall back to `index.html`. Either serve `/api` from the same origin (reverse proxy), or set `VITE_API_BASE_URL` to the API URL and add the UI origin to the API's `CORS_ORIGINS`.

## Telegram Mini App

Telegram requires **HTTPS**. For local testing, tunnel the dev server. The `/api` proxy means one tunnel covers the UI and the API:

```bash
cloudflared tunnel --url http://localhost:5173
```

```bash
ngrok http 5173
```

Then:

1. Set the printed `https://…` URL as `MINI_APP_URL` in the API's `.env`.
2. Recreate the bot so it reloads `.env`: `docker compose up -d --force-recreate bot`.
3. Optionally set the URL as the bot's menu button in @BotFather.

The dev server already accepts tunnel hostnames (`server.allowedHosts: true`). BotFather setup is covered in the API README.

How the Mini App works:

- **Detection.** `window.Telegram.WebApp` comes from `telegram-web-app.js`, loaded in `index.html`. The app counts as "in Telegram" only when `initData` is present (`src/lib/telegram.ts`).
- **Automatic sign-in.** On start, `initData` is posted to `/auth/telegram`.
  - If the account isn't registered, a translated explanation is shown, with a retry and a "sign in with a password" option.
  - Users with a pending password change are still sent to the change-password screen.
- **Layout.** The mobile layout is used, with Telegram's native back button on inner pages.

## Auth & token refresh

- Access and refresh tokens are kept in `localStorage`, falling back to memory.
- The axios interceptor in `src/lib/api.ts`:
  - attaches the access token to every request;
  - on `401 TOKEN_EXPIRED` / `INVALID_TOKEN`, refreshes once (single-flight, shared by concurrent requests) and retries;
  - ends the session if the refresh fails or the account is deactivated.
- A `403 PASSWORD_CHANGE_REQUIRED` refetches `/auth/me`, and the route guard then redirects to `/change-password`.

## Permissions in the UI

UI checks are for **UX only**. The API is the source of truth. `/auth/me` returns the user's effective permission codes.

```tsx
const canCreate = usePermission('users.create')          // hook

<Can permission="users.create">                           // component
  <Button>New user</Button>
</Can>

<RequireAccess permission="users.view" />                 // route guard (router.tsx)
<RequireAccess roles={['superadmin', 'general_manager']} />
```

The menu (`src/layouts/nav.ts`) only shows items whose `permission` / `roles` rule passes.

The **Permissions tab** on a user's page:

- Lists every permission assignable to that user's role, grouped by module, with names and descriptions in Khmer or English.
- Shows a checkbox for each one. It is editable only when the API reports `can_edit`, meaning:
  - you hold `permissions.grant`,
  - the user is in your scope,
  - and you hold that permission yourself.
- Shows all other permissions read-only.

## i18n

- Languages: `km` (default) and `en`. The files are `src/i18n/locales/{km,en}.json`.
- **Switching.** The header switcher changes the language immediately.
  - When signed in, it also saves the choice to your profile (`PATCH /me`).
  - While a password change is pending, the choice stays local only.
- **Your saved language** is applied after sign-in.
- **API errors.** The API returns stable error codes, and `useErrorMessage()` translates them via `errors.<CODE>`, including details such as the lockout time.
- **Permission names** come from the API (`name_km` / `name_en`), and `useLocalized()` picks the one for the current language.

## Adding a new feature (UI side)

After adding the permission to the API registry and guarding the endpoints (see the API README):

1. Create the page in `src/pages/…`.
2. Add a route in `src/router.tsx`, wrapped in `<RequireAccess permission="orders.view">`.
3. Add a menu entry to `NAV_ITEMS` in `src/layouts/nav.ts` with `permission: 'orders.view'`.
4. Wrap action buttons in `<Can permission="orders.create">`.
5. Add the strings to **both** `km.json` and `en.json`, then run `npm run check:i18n`.

## Layout

```
src/
  auth/        AuthProvider (session, Telegram auto-login), usePermission, <Can>, route guards
  components/  UI kit (Button, Field, Card, ConfirmDialog…), badges, LanguageSwitcher, ProfileMenu
  i18n/        i18next setup + locales
  layouts/     AppShell → DesktopLayout (sidebar) / MobileLayout (bottom nav), nav config
  lib/         api client + refresh interceptor, errors, formatting, telegram, types
  pages/       Login, ChangePassword, Home, users/*, AuditLog, Profile, status pages
  router.tsx
```
