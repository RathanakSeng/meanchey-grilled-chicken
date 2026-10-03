# UI Features — Phase 1

What the Mean Chey Grilled Chicken UI (មាន់អាំងមានជ័យ) offers today. One React app serves both the **PC dashboard** and the **Telegram Mini App**.

Phase 1 covers sign-in, user management and access control (feature access levels), plus the **Workstation** features: **Suppliers**, **Customers**, **Production** (batches in three steps, with autosave), the **Production plan** (packaging plans between steps 2 and 3) and **Inventory** (stock updated automatically by production), with production alerts in the header bell and on Telegram.

> The UI hides what a user can't do, for a cleaner experience. **The API enforces every rule**, so hiding things in the UI is never the security boundary.

- [1. Two experiences, one app](#1-two-experiences-one-app)
- [2. Sign-in](#2-sign-in)
- [3. Forced password change](#3-forced-password-change)
- [4. App shell and navigation](#4-app-shell-and-navigation)
- [5. Home](#5-home)
- [6. Workstation (កន្លែងការងារ)](#6-workstation-កន្លែងការងារ)
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
| Navigation | Sidebar: Home · Workstation · Settings (with its sub-pages nested) | Bottom bar: Home · Workstation · Settings |
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
├── Workstation           everyone          /workstation
│   ├── Suppliers         suppliers.view    /workstation/suppliers
│   ├── Customers         customers.view    /workstation/customers
│   ├── Production        production.view   /workstation/production  (batch: /workstation/production/:id?step=1|2|3)
│   ├── Production plan   production_plan.view  /workstation/production-plans  (plan: /workstation/production-plans/:batchId)
│   ├── Inventory         inventory.view    /workstation/inventory  (?tab=history)
│   └── Orders            orders.view       /workstation/orders  (new: /new; order: /:id; edit: /:id/edit)
└── Settings              everyone          /settings
    ├── Users             users.view        /settings/users
    ├── Audit log         superadmin, GM    /settings/audit-logs
    ├── User limits       superadmin        /settings/user-limits
    └── My profile        everyone          /settings/profile
```

- **Each item appears only when the user is allowed to open it.** The rules are unchanged from before: Users needs `users.view`, and Audit log is for the superadmin and general manager.
- **Settings is always shown,** because everyone can open My profile.
- **Workstation is always shown,** even when none of its pages are visible, so its hub can explain that nothing is available yet.
- **Staff** see Home, Workstation and Settings. Workstation shows the "no access yet" message and Settings only My profile, which follows from the permissions with no special handling. Once a general manager (or their supervisor) sets e.g. Suppliers to *View only* on the Access tab, Suppliers appears for that staff member.
- **Desktop sidebar:** Home, Workstation and Settings.
  - While you're anywhere under Workstation or Settings, that section's visible sub-pages are listed indented below it.
  - The current page and its section are highlighted.
- **Mobile / Telegram bottom bar:** exactly three buttons, Home · Workstation · Settings. Settings stays highlighted on every Settings page.
- **Back buttons,** both in-page and Telegram's native one, go to the **parent screen**, not the browser history. For example: user details → Users → Settings → Home, Suppliers → Workstation → Home, and a production batch → Production → Workstation → Home, and a plan → Production plan → Workstation → Home. A deep link opened straight into the Mini App therefore still has a sensible way back.
- **Header:** language switcher (ខ្មែរ / EN), the **notification bell** (§6.4) and an avatar menu.
- **Badges:** *Production plan* shows the number of plans waiting to be set, in the sidebar and on its Workstation card (only for people who can see plans).
- **Avatar menu:** name, role, Telegram username, **My profile** and **Log out**.
- **Permission changes show up quickly.** Menus refresh when Home, Workstation or Settings is opened and the cached permissions are more than a minute old. They also refresh whenever the server answers "no permission", "wrong role" or "out of scope".
- **Old links keep working.** Old addresses (`/users/…`, `/audit-logs`, `/profile`) redirect to their new place under `/settings`, keeping the rest of the address, for example `/users/<id>?tab=permissions`.
## 5. Home

- A welcome banner with the user's name and role badge (plus position for staff).
- Two large tiles, each with an icon, a title and a one-line description. They sit side by side on desktop and stack on mobile:
  - **Workstation (កន្លែងការងារ):** your daily work: suppliers, customers and more;
  - **Settings:** users, permissions and your account.

## 6. Workstation (កន្លែងការងារ)

**Path:** `/workstation`. **Who can open it:** everyone.

A hub with one card per Workstation page the user may open, built from the same menu definition as the sidebar:

| Card | Shown to |
|---|---|
| Suppliers | holders of `suppliers.view` |
| Customers | holders of `customers.view` |
| Production | holders of `production.view` |
| Production plan | holders of `production_plan.view` (with the number of plans waiting) |
| Inventory | holders of `inventory.view` |
| Orders | holders of `orders.view` |

With no visible cards (staff by default) it shows *"You don't have access to any workstation features yet"* with a hint to ask a manager.

### 6.1 Suppliers and customers

**Paths:** `/workstation/suppliers`, `/workstation/customers`. **Who can open them:** users whose Suppliers / Customers access is *View only* or *Full access* (§10): by default general managers and supervisors; staff once a general manager turns it on. Both pages work the same way.

Top to bottom:

1. **Header:** title, total, and **New supplier** / **New customer** (with `*.create`).
2. **Figures (KPI cards):** **Active**, **New this month** and **Deactivated**.
   - Always all visible: three in a row on every screen (compact on phones and in the Mini App, with the label above the number). Grey placeholders while loading.
   - The figures are information only; the list is filtered with the controls below.
   - "This month" follows the calendar month in Cambodia time.
3. **Search and filters:** a search box (name, location or phone; `345 678` finds `012 345 678`), a sort (Name A–Z, Name Z–A, Newest, Oldest) and a **Show deactivated** checkbox. **Deactivated records are left out of the list** unless the box is ticked; then they appear too, dimmed with a *Deactivated* badge.
   - Filters are kept in the address (`?q=…&deactivated=1&sort=…&page=…`), so Back and shared links keep them.
4. **List,** 20 per page:
   - **Desktop:** a table with Name, Location, Phone, Added, Status and a **⋮** menu.
   - **Mobile / Mini App:** cards with name, location, phone and a **⋮** menu.
   - Phones are shown formatted (`012 345 678`, `+855 12 345 678`) as plain text; there is no call button or tap-to-call.
   - Deactivated records are dimmed with a *Deactivated* badge.
   - The **⋮** menu offers **Edit** (`*.update`) and **Deactivate** / **Reactivate** (`*.delete`); without either permission there is no menu.
5. **Empty states:** *No suppliers yet* (with the create button when allowed); *Nothing matches your search* with **Clear filters**; or, when only deactivated records exist, **Show deactivated** (ticks the box). Links from the audit log open the list with the name searched and the box ticked.

**Add / edit** opens a panel: a side drawer on desktop, a bottom sheet on mobile.

- Fields: **Name** (required, up to 150 characters), **Location** (optional, up to 255), **Phone** (optional, numeric keypad).
- Checked before sending, with the server's rules: name required, lengths, phone 8–15 digits (spaces, dashes, dots, brackets and a leading `+` are fine).
- Server errors appear under the field they concern, e.g. *"This phone number is already in use"* under Phone. A phone number can belong to only one **active** supplier (and one active customer).
- On success the panel closes, a confirmation appears above the list, and the list and figures refresh.

**Deactivate / reactivate** asks for confirmation first. Deactivated records keep their history and can be reactivated; reactivation fails if another active record now has the same phone.

### 6.2 Production (ផលិតកម្ម)

**Paths:** `/workstation/production` (list) and `/workstation/production/<id>?step=1|2|3` (a batch). **Who can open them:** Production access *View only* or higher (§10): by default general managers and supervisors; staff once a general manager turns it on.

A **batch** (code `PR-YYYYMMDD-NNN`) goes through three steps: **Intake** (ការនាំចូល) → **Processing** (ការផលិត) → **Standardize** (ការវេចខ្ចប់). Each step is filled in as a draft that **saves itself**, and is locked with **Finish step**. A step opens only once the previous one is finished. **Between steps 2 and 3 a planner sets and confirms the packaging plan** (§6.3): step 3 stays locked until then.

**Dates are recorded automatically.** Finishing a step records today's date for it (Cambodia calendar): **Import date** (ថ្ងៃនាំចូល) for step 1, **Production date** (ថ្ងៃផលិត) for step 2, **Packing date** (ថ្ងៃវេចខ្ចប់) for step 3. Nobody types or changes them; each form says so at the top (*"ថ្ងៃនាំចូល will be recorded when you finish this step"*). Reopening a step clears its date and the dates of the later steps it sends back to draft; finishing again records the new day. The batch code keeps the day the batch was started.

**List page**

1. **Header:** title, total and **New production** (Record or Full access). It creates the batch at once and opens step 1.
2. **Figures:** *In progress*, *Completed today*, *Chickens this month*, *Rejected pieces this month* (Cambodia calendar; cancelled batches aren't counted). Four in a row on large screens, 2 × 2 on phones and in the Mini App, all visible without scrolling.
3. **Quick filters** as chips: **Waiting for step 2**, **Waiting for plan** (step 2 finished, plan not confirmed yet) and **Waiting for step 3** (plan confirmed): the batches ready to pick up. Plus a status filter (All · In progress · Completed), a **Show cancelled** checkbox, a **Date** (ថ្ងៃ) range that *matches any step date* (import, production or packing; a batch with no finished step matches on the day it was started) and a search box (batch code or supplier). **Cancelled batches are left out of the list** unless *Show cancelled* is ticked; then they're added, dimmed, to whatever status is chosen. All filters are kept in the address.
4. **List,** 20 per page, latest date first: batch code, the three dates (*Import date · Production date · Packing date*, "—" until recorded), supplier, step dots (●●○: filled = finished, ringed = draft), number of chickens and a status badge. A table on desktop (it scrolls sideways inside its card if the columns don't fit); on mobile, cards with one date line: the latest recorded date and its label (*"ផលិត 29 Sept"*), or *"Started 29 Sept"*. Tapping a batch opens it.

**Batch page**

- **Header:** code, status badge and the recorded dates as compact chips (*"នាំចូល 28 Sept · ផលិត 29 Sept · វេចខ្ចប់ —"*; *"Started 29 Sept"* before any step is finished), and a **⋮** menu with **Reopen \<step\>** for every finished step (Full access) and **Cancel batch** (general manager and superadmin only; in-progress batches, asks for a required reason).
- **Plan card** under the stepper, once step 2 has been finished: *Packaging plan* with its status (**Waiting for plan** / **Confirmed** / **Completed**, or *No plan (before plans existed)* for batches finished before plans existed), the planned packs (*"148 × 4-piece · 4 × 2-piece"*) and **Open plan** for people who can see plans.
- **Stepper 1 · 2 · 3** (✓ when finished, with the step's date: *"Finished · 27 Sept"*; on phones the date sits under the name). All three cards keep the same height. Tapping a step shows it; steps not started yet are disabled. On mobile one step is shown at a time.
- A finished step shows a **read-only summary** with its date and *Finished by … · time* (*"ថ្ងៃនាំចូល · 27 Sept 2026 · Finished by …"*). **Reopen \<step\>** (⋮ menu) works on any finished step in one action: it and every later finished step go back to draft with their values kept, and must be finished again in order. The confirmation says which steps, e.g. *"Reopen Intake? Processing and Standardize will go back to draft and need to be finished again."* A completed batch is in progress again until then. The page then switches to that step. The current step shows its **form** to users with Record or Full access; with *View only* every step is read-only (a notice says so).
- Cancelled batches show the reason and are read-only; completed ones show when they were completed.

**Step 1: Intake.** Type (ប្រភេទ: Chicken), supplier (a searchable list of active suppliers; no Suppliers access needed), weight (kg) and number of chickens. No date field: the import date is recorded at Finish.

**Step 2: Processing.** Wings and thighs weight (kg), each next to its **count, locked at 2 per chicken** (lock icon; set by the server from step 1), the four by-products in kg (gizzard កោះមាន់, liver ថ្លើមមាន់, heart បេះដូងមាន់, head ក្បាលមាន់; 0 is allowed) and the marinade in grams. The yield (wings + thighs ÷ imported weight) is shown live and in the summary.

**Step 3: Standardize.** While the plan isn't confirmed, step 3 shows *"Waiting for the packaging plan"* (with **Open plan** for plan holders) instead of the form; the API refuses saves too. Then: **4-Piece Packs** (កញ្ចប់ ៤ ដុំ, *1 × 4-piece = 2 wings + 2 thighs*) and **2-Piece Packs** (កញ្ចប់ ២ ដុំ, *1 × 2-piece = 1 wing + 1 thigh*) with a live breakdown, rejected wings and thighs, a **Plan vs actual** panel (planned and actual per pack size, ⚠ where they differ), and a **balance meter** per piece type (*"Wings: 3 left to assign"*, *"2 too many"*, *All assigned*). For each by-product: the produced kg, **carry forward** (យកទៅបន្ត) and **rejected** (ខូច/មិនប្រើ) inputs, and a per-row indicator. The comment is optional, **unless the packs differ from the plan**: then an amber notice says *"Different from the plan — add a comment."*, the comment becomes required (*Comment \**) and Finish stays disabled (*"Comment required: packs differ from the plan."*). The API enforces it too. The step 3 summary shows the plan vs actual panel.

**Finish step** is disabled until the step is complete; a list under the form says what's missing (*"Fill in: Weight, Supplier"*, *"Wings don't add up yet"*). It asks for confirmation: *"The step is locked after finishing. Only someone with Full access can reopen it."*

- Wings and thighs must balance exactly: 2 × big + small + rejected = count. The API enforces this too.
- **By-products must balance exactly** (carry forward + rejected = produced kg). **This rule is enforced by the UI only**; the API accepts unbalanced by-products (it may be relaxed later).
- Numbers: kg up to 3 decimals, grams up to 1, counts whole; a comma works as the decimal point. Weight fields open the decimal keypad, counts the numeric one, with large touch targets. Invalid input is flagged under the field and isn't sent.
- On mobile and in the Mini App, **Finish step** sits in a sticky bar above the bottom navigation.

**Autosave** (a status in the step header):

| Status | Meaning |
|---|---|
| *Saving…* | changes are waiting (1.5 s after the last keystroke) or being sent |
| *Saved just now* / *Saved at 14:05* | on the server |
| *Offline — saved on this device* | no connection; sent automatically when back online |
| *Couldn't save — retrying* | the server failed; retried every few seconds |

- **Closing the Mini App or switching apps doesn't lose input:** pending changes are sent immediately when the page is hidden or closed, and every unsent change is also kept on the device. On the next visit, changes that didn't reach the server are resent automatically; if the batch changed on the server in the meantime, the app asks **"Restore unsaved changes?"** (Restore / Discard).
- **Two people editing the same step:** if someone else saved first, the step shows *"Someone else saved this batch first"* with the fields they changed, keeps your values on screen, and lets you **Keep my values** (save over theirs) or **Use their version**.
- Finished steps never autosave. Finishing first sends any pending changes.

### 6.3 Production plan (ផែនការវេចខ្ចប់)

**Paths:** `/workstation/production-plans` (list) and `/workstation/production-plans/<batch id>` (a plan). **Who can open them:** Production plan access *View only* or *Full access* (§10): by default general managers; supervisors once a general manager turns it on; never staff. Plans are created by finishing step 2; step 3 can't start until the plan is confirmed.

**List:** status chips **Waiting for plan** (default, with the count) · **Confirmed** · **Completed** · **All**, and a search (batch code or supplier), kept in the address. Each row / card: batch code, production date, supplier, chickens, wings / thighs, the planned packs and a status badge. Cancelled batches never appear.

**Plan page:**

- **Header:** code, status, production date and supplier, and **Open batch**.
- **Processed (step 2)**, read-only: wings and thighs (kg and pieces), each by-product (kg, catalog names), marinade (g), number of chickens.
- **Packaging plan:** with *Full access* and while it can change: **4-Piece Packs** and **2-Piece Packs** (numeric keypad), an optional note, and a live meter *"Uses 296 of 300 wings · 296 of 300 thighs"* that turns red when the plan needs more pieces than were produced (Save and Confirm are then disabled; the API checks the same rule). **Save** keeps the values; **Confirm plan** asks *"Confirm the plan? … Step 3 can start once the plan is confirmed."*. A confirmed plan shows *Confirmed by … · time* and stays editable with **Save** (it stays confirmed) until step 3 is finished.
- **Read-only** for *View only*, completed batches (with the actual packs and comment beside the plan) and cancelled batches. *"No plan: this batch was finished before packaging plans existed."* for older batches; *"The plan can be set once processing (step 2) is finished."* before that.
- **Reopening:** reopening step 1 or 2 puts the plan back to *Waiting for plan* (values kept) and step 3 is locked again; reopening step 3 keeps it confirmed.
- **Someone else changed the batch:** the plan reloads with a notice (*"Someone else changed this batch. The plan has been reloaded — check the values and try again."*).

### 6.4 Notifications (the bell)

A bell in the top bar (desktop and mobile) with the number of unread notifications, refreshed every minute and when the window gets focus. It opens a dropdown on desktop and a bottom sheet on mobile: the latest notifications, newest first, each with an icon, its text in the current language and the time; unread ones are highlighted with a dot.

| Icon | When | Text | Opens |
|---|---|---|---|
| ✅ | Step 2 finished | *"PR-…: processing finished — 150 chickens → 300 wings, 300 thighs. Set the packaging plan."* | the plan |
| 🎉 | Step 3 finished as planned | *"PR-…: production completed as planned — 148 × 4-Piece Packs, 4 × 2-Piece Packs."* | the batch, step 3 |
| ⚠️ | Step 3 finished, different from the plan | *"PR-…: production completed, different from the plan. Planned 148 / 4, actual 147 / 6."* and the comment | the batch, step 3 |

"again" is added when a step was finished again after a reopen. Tapping one marks it read and opens it; **Mark all as read** clears the count. Empty: *"No notifications yet."*

| 🚚 ✅ ↩️ 📦 | An order out for delivery, delivered, returned, return reviewed (§6.6) | e.g. *"OR-…: Dara Shop returned items — 2 × 4-Piece Packs. Review the return."* and the reason | the order |

**Who gets them:** production alerts go to everyone with Production plan access, order alerts to everyone with **Order returns** (general managers, supervisors given access, and the system account), also on **Telegram** when their Telegram account is linked, with an **Open plan** / **Open batch** / **Open order** button into the Mini App. Staff get none.

### 6.5 Inventory (ស្តុក)

**Path:** `/workstation/inventory`: main tabs **Stock** (ស្តុក, `?tab=stock&section=raw|processed|packed|wasted`) and **History** (ប្រវត្តិ, `?tab=history`). **Who can open it:** `inventory.view` (GM and supervisors by default; staff when given *View only*). Lazy-loaded.

**Production items are read-only.** Every item changes only through production (Finish, reopen, cancel) and orders (Start delivery, return review, §6.6); nobody sets stock by hand, so there is no Set button anywhere. **History** (every movement) needs **Inventory history** (`inventory.history`), which is off by default: without it there is no tab bar and Stock shows directly, item sheets show no recent changes, and batch pages show no Stock changes.

Stock updates **automatically** as production steps are finished; reopening a step or cancelling a batch undoes what it did. Nothing can go below zero.

**Stock tab**: four sub-tabs, each a grid of item cards, like a menu of products.

- **Sub-tabs:** **Raw** (វត្ថុធាតុដើម: Chicken) · **Processed** (ផលិត: Wings, Thighs, Gizzard, Liver, Heart, Head) · **Packed** (វេចខ្ចប់: 4-Piece Packs, 2-Piece Packs, Gizzard, Liver, Heart, Head) · **Wasted** (ខូចខាត: Wings, Thighs, 4-Piece Packs, 2-Piece Packs, by-products). Which tab an item belongs to comes from the API, so a new by-product appears in the right one on its own.
- **Pill bar**, lighter than the main tabs (pills on a grey track, no underline): full width with equal pills on phones and in the Mini App (scrolls sideways if a label doesn't fit), compact and left-aligned from tablets. The selected Wasted pill is muted red, so it's never mistaken for stock.
- **Stock badge** on each pill: how many items in that tab have stock (count or kg above 0); no badge at 0 or while loading. It updates in place when production changes stock.
- The selected sub-tab is in the URL (`?tab=stock&section=processed`; default **Raw**), so refresh, Back (e.g. after opening a batch from an item's history) and shared links keep it. Switching to History and back keeps it too.
- A sub-tab without any items (only possible for a future section) shows a short empty state.
- **Grid:** 2 cards per row on phones and in the Mini App, 3 from tablets, 4 on laptops, 6 on wide screens; every card in a row has the same height.
- **Card:** a picture; a small **ខូចខាត / Wasted** corner badge in the Wasted tab only (the sub-tab already says processed / packed); the **short name** (*ថ្លើមមាន់*, not *ថ្លើមមាន់ (ផលិត)*: the sub-tab says it), up to 2 lines; the **big number** (the count for Chicken, Wings, Thighs and Packs; the kg with its unit for by-products, e.g. *12.500 គ.ក*); for items with both units the kg under the count (*"210.000 គ.ក"*, **"≈"** with the tooltip *"Estimated from the batch's average weight"* for wasted pieces); and the last change (*"Updated 2 h ago"*, *"No changes yet"*). No action button: production items aren't changed by hand.
- **Zero** balances: the card is dimmed (grey number and picture), still tappable.
- Wasted cards show the stock picture in grey.
- **Day one:** a note above the sub-tabs says *"Stock starts at zero. It updates automatically as production steps are finished."* while every balance is 0.
- While loading: the sub-tabs (without badges) and grey placeholder cards in the grid.
- **Tap a card** → the **item sheet** (drawer on PC, bottom sheet on phones): big picture, full name (e.g. *Liver (processed)*), its sub-tab as a label (red for Wasted), balance (count and / or kg), last change, and:
  - **From production** (ពីផលិតកម្ម), for everyone with Inventory: one row per batch that currently contributes, oldest first: the batch code (opens the batch at that step) · the last step that still contributes, and its count and / or kg (**"≈"** when estimated); then a **Total** line equal to the balance. Nothing to show: *"No stock from production right now."* Example: after the 50-chicken batch finishes step 2 it leaves Chicken and appears under Wings and Thighs.
  - With **Inventory history** only: the item's **last 20 changes** (time, + green / − red, new balance, source: the batch code linking to the batch · step, *"Reversed: reopen / cancelled"*, by whom) and **See full history**, which opens the History tab filtered by that item (the sub-tab is kept for coming back).
- Numbers use the same formatting as the rest of the app: counts with thousands separators, kg always with 3 decimals.

**History tab**

- Movements, newest first, 50 per page (the same rows as in the item sheet). Filters (kept in the URL): item, section (stock / wasted), type (production, order, return), date range, part of a batch code. Only with **Inventory history**.
- Each row: item (*"Wasted: Wings"* for wasted items), the change (+ green / − red; count and kg, "≈" when estimated), the new balance, the source and who did it:
  - production: the **batch code** (opens the batch at that step) · step name;
  - a reversal: *"Reversed: reopen"* or *"Reversed: cancelled"* · batch code · step;
  - an order: *"Order OR-… · from PR-…"* (the order and the batch the packs were taken from), or a return: *"Return OR-… · to PR-…"*;
  - an adjustment: *"Adjustment — reason"*.
- Movements made by the superadmin read *System*.

**On the production batch page**

- With **Inventory history** only (the API sends the data only then): a **Stock changes** card under the step lists what each finished step added (+, green) or removed (−, red), step by step. Reopened steps drop out of it. Batches from before inventory existed show *"Not counted in inventory (before inventory started)."*
- **Finish, Reopen and Cancel** can be refused when stock is short; the message names each item, e.g. *"Not enough Chicken in stock: 10 available, 100 needed."* (in the step's error area, the reopen dialog or the cancel sheet). Nothing changes.

### 6.6 Orders (ការបញ្ជាទិញ)

**Paths:** `/workstation/orders` (list), `/workstation/orders/new`, `/workstation/orders/:id`, `/workstation/orders/:id/edit`. **Who can open them:** `orders.view` (GM and supervisors by default; staff when given Orders); New needs `orders.create`, Edit `orders.update`. Lazy-loaded (one chunk per page). Menu icon: receipt.

```
Created ──► Delivering ──► Delivered ─┬─► Success                (everything accepted)
   │        (stock out)               └─► Return pending ──► Partly / Fully returned
   └─► Cancelled (only while Created)
```

**List**

- **Figures:** Created · Delivering · Return pending · Delivered this month (tap one of the first three to filter by it).
- **Status chips:** All · Created · Delivering · Return pending · Completed (success, partly or fully returned) · Cancelled. **Search** (order code or customer), **Customer** (for people who record or edit orders) and a **delivery date** range. Everything is in the URL (`?status=&customer=&from=&to=&q=&page=`), 20 per page.
- Phones: a card per order (code, customer, status badge, delivery date · driver, ▢ white / ■ black box counts). Desktop: a table with the same columns. **New order** with `orders.create`.

**Order form** (create; edit while Created with `orders.update`)

- **Customer** picker (active customers, search by name or phone; no Customers access needed), **Delivery date** (today), **Driver** (optional: active staff and supervisors), **Note**.
- **Boxes builder:** **+ White box** and **+ Black box** add a card (*Box 3 · White box*) with item lines: the item (4-Piece Packs, 2-Piece Packs, packed by-products, each with the stock available, e.g. *"4-Piece Packs (12 in stock)"*; an item already in that box is disabled) and the quantity (whole numbers for packs, kg with up to 3 decimals for by-products), **×** to remove a line, **Add item**; box actions **Duplicate** (inserted after it) and **Remove**.
- **Live summary:** per colour (*White boxes: 2* — 4-Piece Packs 5, 2-Piece Packs 1, Liver (packed) 0.150 kg), then the **grand total**; an amber line when a total is above the stock (*"Only 12 × 4-Piece Packs in stock."*). Sticky beside the form on desktop; on phones a bar at the bottom (*Summary · Boxes: 3*, with ⚠ when short) that opens it, with the Save button.
- **Checks before saving** (the same as the API's): a customer, a date, at least one box, at least one item per box, an item and a valid quantity on every line, an item at most once per box. Mistakes are outlined in red with a short message, and *"Check the highlighted fields."* above Save.
- Saving opens the order. A stock warning doesn't block saving; stock is only taken at Start delivery. If someone else changed the order meanwhile, the form reloads it with a notice.

**Order page**

- **Header:** code, status badge, customer; **⋮** with **Edit** (`orders.update`) and **Cancel order** (`orders.cancel`) while Created.
- **Details:** customer (name, phone as a call link, location), delivery date, driver, note. While Created with too little stock: an amber list (*"Only 12 × 4-Piece Packs in stock."*).
- **Main action** by status (a full-width button under the header on phones):
  - Created (`orders.create`): **Start delivery** → a confirmation (*"The 3 boxes for Dara Shop leave stock now (oldest batches first). This can't be undone."*); a stock refusal names each item (*"Not enough 4-Piece Packs in stock: 7 available, 9 needed."*).
  - Delivering (`orders.create`): **Mark delivered** → a sheet: **Everything accepted**, or **Some items returned** with a quantity per item (the delivered amount shown next to it, at most that) and a required **reason**.
  - Return pending (`orders.review_returns`): **Review return** → a sheet: the reason, then per item what came back with **Back to stock** and **Wasted** (they must add up, shown in red until they do); **All to stock** / **All wasted** fill every item. Without the permission: *"Waiting for a manager to review the returned items."*
- **Status** timeline: Created → Out for delivery → Delivered (*Delivered, items returned*) → Return reviewed, or Created → Cancelled, each with its time and who did it ("System" for the system account).
- **Summary** (per colour and grand total), **Boxes** (each box with its lines), and after a return **Returns** (delivered / returned and, once reviewed, back to stock in green and wasted in red, with the reason).
- **Cancel order:** a sheet with the reason pre-filled *"Customer cancelled"* (required).
- **Conflicts:** if someone else moved the order on, the page shows the current order with *"Someone else changed this order. It has been reloaded; check it and try again."*

**Elsewhere**

- **Inventory:** two new **Wasted** cards, 4-Piece Packs and 2-Piece Packs (packs returned damaged). The item sheet's *From production* breakdown already reflects orders (packs leave the oldest batches first; returns go back to theirs). History (with Inventory history) shows **Order OR-… · from PR-…** and **Return OR-… · to PR-…** rows linking to the order and the batch, and the Type filter has Order and Return.
- **Production batch page:** reopening or cancelling a batch whose packs already left in orders is refused: *"4-Piece Packs from this batch were already delivered in OR-20261003-001 — can't reopen or cancel it."*
- **Bell and Telegram** (holders of Order returns): 🚚 *"OR-…: for Dara Shop is out for delivery — 2 white / 1 black boxes."* · ✅ *"…delivered to Dara Shop, everything accepted."* · ↩️ *"…Dara Shop returned items — 2 × 4-Piece Packs. Review the return."* (with the reason) · 📦 *"…return reviewed — Partly returned (1 × 4-Piece Packs to stock, 1 × 4-Piece Packs wasted)."* Each opens the order.
- **Audit log:** Order created / edited / cancelled (reason) / out for delivery / delivered (*Everything accepted* or *Items returned* with the reason) / return reviewed (partly / fully), with the order code linking to the order; record type **Order** in the filter.

## 7. Settings

**Path:** `/settings`. **Who can open it:** everyone.

- A hub with one card per Settings page the user may open. Each card has an icon, a title and a one-line description:

  | Card | Shown to |
  |---|---|
  | Users | holders of `users.view` |
  | Audit log | superadmin, general managers |
  | User limits | superadmin |
  | My profile | everyone |

- The cards come from the same menu definition as the sidebar, so a new Settings page appears here automatically.

### 7.1 User limits (ចំនួនអ្នកប្រើប្រាស់), superadmin only

**Path:** `/settings/user-limits`. How many **active** users each role may have: **General manager** (default 2), **Supervisor** (default 3) and **Staff** (default 10).

- One row per role: *"2 / 3 active"*, a number input (1–999) and **Save**, with an inline *Saved* or error. Supervisor and Staff also have an **Unlimited** checkbox; general managers always have a limit of at least 1.
- **Over the limit** (after lowering it): an amber warning on the row, e.g. *"4 active — above the limit of 3. No new supervisors can be added until someone is deactivated."* Nobody is deactivated automatically.
- *Last changed by … · time* under each changed row, and a note that only active users count.
- Changes are in the audit log as *Changed user limit* (*"Staff: 10 → 12"*), visible to the superadmin only.

## 8. Users

**Path:** `/settings/users` (create: `/settings/users/new`). **Who can open it:** users with `users.view`. The list only contains users the viewer manages:

| Viewer | Sees |
|---|---|
| Superadmin | general managers, supervisors, staff |
| General manager | supervisors, staff (not other general managers) |
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
- **New user** button, shown with `users.create`. Supervisors start without it (Staff management *View only*); a GM allows it per supervisor with *Record* or *Full access*. Without it the list is read-only, with no hint naming other roles.
- **Capacity line** under the total, for the roles the viewer manages: *"Supervisors 2 / 3 · Staff 7 / 10"* (*no limit* when unlimited).

**Create a user** (`users.create`)

- **Role:** limited to the roles the viewer may create, each with its capacity (*"Supervisor (3 / 3) — full"*). A full role can't be picked, and a note says *"Roles marked full have reached their limit — deactivate someone or ask for the limit to be raised."* It defaults to the lowest role with a free slot, usually staff. If **every** role the viewer can create is full, the page shows that message instead of the form.
- **Position (job title):** staff only, and required for them.
  - Free text, up to 50 characters, in any language. Examples: `Grill cook`, `Cashier`, `អ្នកដឹកជញ្ជូន`.
  - As you type, positions already used in your scope are suggested, which keeps spelling consistent.
  - Extra spaces are removed; case and Khmer text are kept as typed.
  - The hint says it's a **job title only**: position never changes what a user can see or do. Access comes only from role and permissions.
- **Other fields:** full name, Telegram username, optional phone, language.
- **Live login preview:** "Signs in as: sok_dara" shows how the username will be normalized.
- **Initial-password note:** the initial password is the Telegram username, and it must be changed at first sign-in.
- **After saving,** it opens the new user's page with a confirmation showing the initial password.

**Edit a user** (`users.update`; supervisors only at Staff management *Full access*)

- Same fields; the role isn't edited here (see **Change role** on the user's page, §9). Staff can be given a new position at any time; it has no effect on their access.
- If the user is linked to Telegram and you change their username, a warning says the link will be removed.

## 9. User detail

**Path:** `/settings/users/<id>` (edit: `/settings/users/<id>/edit`, tabs: `?tab=access`, `?tab=permissions`).

- **Header:** name, `@telegram`, role/position badge, status badges.
- **Actions**, each shown only with the matching permission. All destructive actions ask for confirmation in a dialog.

  | Action | Permission |
  |---|---|
  | **Edit** | `users.update` (supervisors: only when a GM set Staff management to Full access) |
  | **Reset password** | `users.reset_password` (general manager) |
  | **Change role** | general manager (staff ↔ supervisor) and superadmin (general manager / supervisor / staff) |
  | **Deactivate** / **Reactivate** | `users.delete` (general manager; supervisors never) |

  - Reset password sets the password back to the Telegram username. The dialog explains the user will be signed out everywhere and must choose a new password.
  - Deactivate / Reactivate is a soft on/off switch. A deactivated user is signed out immediately and frees a slot in their role. Reactivating needs a free slot: otherwise *"The supervisor limit (3) is reached."*
  - **Change role** opens a panel (drawer on PC, bottom sheet on phones) listing the roles you can move this user to. Choosing *Staff* asks for a position (with suggestions). A note explains that access is reset to the new role's defaults, adjustable afterwards on the Access tab. Each role shows its capacity (*"Supervisor (2 / 2)"*); for an active user a full role is disabled with *"Limit reached — deactivate someone or ask for the limit to be raised."* (an inactive user can be moved, and needs a free slot when reactivated). The user stays signed in; their menus update at the next refresh.

- **Details tab:**
  - full name, Telegram username and whether it's **linked** to a Telegram account;
  - role, position (shown exactly as entered, never translated), phone, language;
  - created, updated and deactivated dates;
  - locked-until time, if the account is locked.
- **Tabs**, by viewer (§10):

  | Viewer | Details | Access | Permissions (advanced) |
  |---|---|---|---|
  | General manager (supervisor / staff) | ✅ | ✅ | — |
  | Supervisor (staff) | ✅ | ✅ with Staff access (default) | — |
  | Superadmin (general manager, supervisor, staff) | ✅ | ✅ | ✅ |

  A supervisor opening a staff member without *Edit* (the default) sees a read-only page: Details, plus the Access tab when it has Staff access. Nobody sees an Access tab on their own profile, and staff never see one.

  When the superadmin opens the **general manager**, the Access tab shows the GM's levels for Suppliers, Customers, Production, Production plan and Staff management (only the superadmin can change them); the GM-only powers are on Permissions (advanced).

  A `?tab=` the viewer can't open falls back to Details.
- Success and error messages are shown inline and are translated.

## 10. Access tab and Permissions (advanced)

### Access tab (ការចូលប្រើ)

How general managers decide what supervisors and staff can use (and how the superadmin decides what each general manager can use), and how **supervisors** decide what their **staff** can use. Shown when the viewer may manage access (*can manage features*) and at least one feature applies to the user. A general manager can set **any level of any feature** available to that user's role; nothing here depends on the general manager's own permissions.

- **Supervisors** (with **Staff access**, on by default) see the Access tab of **staff** only, with the same layout: Suppliers, Customers and Production. They can give a level **up to their own** (what a GM or the superadmin gave them): higher segments are disabled, with the tooltip *"Higher than your own access"* (*ខ្ពស់ជាងសិទ្ធិរបស់អ្នក*). *Off* and lower levels are always available, also for a level a GM set higher. If the server still refuses (the supervisor's access was lowered meanwhile), the message reads *"You can't give more access than you have."* When a GM lowers the supervisor later, levels the supervisor already gave stay as they are.
- **Grouped by menu:** **Workstation** (Suppliers, Customers, Production, Production plan: GM and supervisors only), then **Settings** (Staff management: supervisors, and general managers when the superadmin views them; **Staff access**: supervisors only).
- Each row: the feature's name and a one-line description (from the server, in the current language), and a segmented control with the levels the server lists for that feature: **Off · View only · Full access** (*បិទ · មើលតែប៉ុណ្ណោះ · ពេញលេញ*); for Production and Staff management **Off · View only · Record · Full access** (*បិទ · មើលតែប៉ុណ្ណោះ · កត់ត្រា · ពេញលេញ*); for Staff access **Off · Full access**, described as *"Can set what staff can use, up to their own access."*
- A legend at the top: *View only* = can see the list; *Record* = can start batches and fill in steps, but can't reopen finished steps (shown when Production is listed); *Full access* = can add, edit and deactivate, and in Production also reopen finished steps. When Production plan is listed: *"Production plan: View only = see plans and receive production alerts; Full access = also set and confirm plans."* When Staff management is listed: *"Staff management: View only = see staff; Record = also add staff; Full access = also edit their info."* (supervisors never deactivate people). When Staff access is listed: *"Staff access: Full access = can set what staff can use, up to their own access."*
- **Each click saves** immediately, with a spinner on that row. On error the previous level comes back and a translated message is shown.
- From *Off*, *View only* has a dashed outline as the suggested next step; it still takes a click.
- **Custom:** if a user's permissions match no level (only possible through the superadmin's detailed permissions), a neutral *Custom* badge is shown and no level is selected. Picking a level replaces it.
- **Inventory history** (Off · View only, under Workstation) appears only where the viewer may give it: the superadmin on general managers and supervisors, and a general manager on supervisors **only while that GM has it**. A GM without it never sees the row, with no hint.
- Rows are disabled only when the user is deactivated; single segments only when above a supervisor's own access. No explanation mentions other roles.
- Defaults: supervisors start with Suppliers, Customers and Production at **Full access**, **Production plan Off**, **Staff management View only** and **Staff access Full access**; staff with everything **Off**; general managers at **Full access**. Supervisors who had Staff management at Full access before this default changed were moved to View only once (audit log: *"New default for supervisors"*, by System).
- **General manager as the target** (superadmin only): a hint under the legend says *"Deactivating users, resetting passwords, managing access and cancelling batches are set in Permissions (advanced)."* Lowering Staff management takes creating / editing users (at *Off*, the Users list) away from the GM.
- Changes take effect on the user's next menu refresh (within a minute, or at once on their next "no permission" answer). If you change your own access, your menus refresh immediately.
- **Every row has the same columns, in the same order:** Off · View only · Record · Full access. A feature without a level (Record exists only for Production and Staff management; Staff access has only Off and Full access) shows a muted "—" in that column (tooltip: *Not available for this feature*), so each level sits in the same place for every feature. On large screens the columns have one fixed width and line up exactly; on tablets, phones and in the Mini App the control sits under the name, full width, with large touch targets, as a 2 × 2 grid on phones. If no feature on the tab has Record, the column isn't shown.

### Permissions (advanced), superadmin only

Only for the superadmin. Shows the detailed permissions under the feature levels: grouped by module, each with its localized name, description and code, a checkbox, and a lock reason from the server when it can't be changed (e.g. the user is deactivated). Clicking a checkbox grants or revokes that one permission immediately. General-manager-only permissions (deactivate users, reset passwords, manage access, cancel production batches) are managed here. Revoking *manage access* from the GM removes the GM's Access tab.

Supervisors never see detailed permissions; they see feature levels only on the Access tab of their staff (with Staff access). Staff never see any permission or access information.

## 11. Audit log

**Path:** `/settings/audit-logs`. **Who can open it:** general managers and the superadmin. General managers don't see entries made by the superadmin (nor detailed permission changes).

- A chronological list of security events:
  - sign-ins and failed sign-ins;
  - lockouts;
  - password changes and resets;
  - user creation, edits, role changes (e.g. *"Staff → Supervisor"*), deactivation and reactivation;
  - access changes (*Changed access*), shown as e.g. *"Suppliers: View only → Full access"*;
  - detailed permission grants and revokes, including automatic ones on deploy: **superadmin only** (general managers see access changes instead);
  - profile updates;
  - suppliers and customers added, edited, deactivated and reactivated;
  - production: batch started, step finished and step reopened (*"Step 1 · Intake"*, plus *"Also back to draft: step 2, 3"* when later steps were reopened with it), batch cancelled (with the reason). Draft saves aren't logged;
  - packaging plans: *Edited packaging plan* (field changes in the details) and *Confirmed packaging plan* (*"148 × 4-piece · 4 × 2-piece"*), linked to the batch;
  - orders: created, edited, cancelled (with the reason), out for delivery, delivered (*Everything accepted* / *Items returned* and the reason), return reviewed (*Partly* / *Fully returned*), linked to the order;
  - the system account linking or unlinking its Telegram (superadmin only).
- **Filters:** record type (All · Suppliers · Customers · Production batches · Orders) and action type.
- Each entry shows:
  - the time, in the current language's format;
  - the action, as a translated badge, red for failures and locks;
  - **By** (actor) and **User** (target), linking to the user. Actions by the system show **System** (ប្រព័ន្ធ), without a link;
  - for supplier / customer entries, the **record**: its type and current name, linking to the Suppliers / Customers page with that name already searched (including deactivated records); for production entries, the batch code, linking to the batch;
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

**Telegram** (system account only)

- Status *Telegram linked* / *Telegram not linked yet*. **Link Telegram** creates a one-time link and shows **Open the bot** (*"Opens the bot; valid for 10 minutes. Tap Start there."*); after tapping Start in Telegram, the card shows *Linked* when you come back to the window. **Unlink** (with confirmation) stops the alerts on Telegram. Other accounts link Telegram by signing in to the Mini App, as before.

**Change password**

- Current password, new password and confirmation, with the same rules as §3.

**Reset my password** (general manager)

- Returns your password to your Telegram username and signs you out on all devices. You must change it at next sign-in. (The superadmin's reset returns it to its initial password instead.)
- After confirming, you're taken to the login page with a message telling you which password to use.

## 13. Language (Khmer / English)

- **Khmer is the default.** English is fully supported: every label, message, role, audit action and error, including the supplier / customer / production pages, their figures and autosave states. Positions are free text and are shown as entered.
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
| Home, Workstation, Settings hub | ✅ | ✅ | ✅ | ✅ |
| Settings → My profile | ✅ | ✅ | ✅ | ✅ |
| Settings → Users (list / detail) | ✅ all below | ✅ supervisors, staff | Staff management ≥ View only (default View only): staff | ❌ |
| Add staff | ✅ | ✅ | Staff management ≥ Record (only if allowed; default View only) | ❌ |
| Edit staff info | ✅ | ✅ | Staff management = Full (only if allowed) | ❌ |
| Change role (promote / demote) | ✅ GM ↔ supervisor ↔ staff | ✅ supervisor ↔ staff | ❌ | ❌ |
| Settings → User limits (role limits) | ✅ | ❌ | ❌ | ❌ |
| Role capacity in the users list and forms | ✅ all three roles | ✅ supervisors, staff | ✅ staff | ❌ |
| Deactivate / reactivate users | ✅ | ✅ | ❌ never | ❌ |
| Reset others' password | ✅ | ✅ | ❌ never | ❌ |
| Reset own password | ✅ | ✅ | ❌ | ❌ |
| User detail → Access tab | ✅ | ✅ (supervisors, staff) | Staff access = Full (default ✅): staff only, up to its own levels | ❌ |
| Set staff access (Suppliers, Customers, Production of staff) | ✅ | ✅ | ✅ default (Staff access), never above its own | ❌ |
| User detail → Permissions (advanced) | ✅ | ❌ | ❌ | ❌ |
| Settings → Audit log | ✅ everything | ✅ without detailed permission entries | ❌ | ❌ |
| Workstation → Suppliers (list, figures) | ✅ | ✅ | Suppliers ≥ View only (default Full) | Suppliers ≥ View only (default Off) |
| Add / edit / deactivate suppliers | ✅ | ✅ | Suppliers = Full (default) | Suppliers = Full |
| Workstation → Customers (list, figures) | ✅ | ✅ | Customers ≥ View only (default Full) | Customers ≥ View only (default Off) |
| Add / edit / deactivate customers | ✅ | ✅ | Customers = Full (default) | Customers = Full |
| Workstation → Production (list, batches, figures) | ✅ | ✅ | Production ≥ View only (default Full) | Production ≥ View only (default Off) |
| Start batches, fill in and finish steps | ✅ | ✅ | Production ≥ Record (default Full) | Production ≥ Record |
| Reopen finished steps (later steps go back to draft) | ✅ | Production = Full (default; set by the superadmin) | Production = Full (default) | Production = Full |
| Cancel production batches | ✅ | ✅ | ❌ never | ❌ never |
| Workstation → Production plan (list, plans), production alerts (bell, Telegram) | ✅ | Production plan ≥ View only (default Full) | Production plan ≥ View only (default Off) | ❌ never |
| Set and confirm packaging plans | ✅ | Production plan = Full (default) | Production plan = Full | ❌ never |
| Workstation → Inventory (stock, wasted, item sheet with the per-batch breakdown) | ✅ | Inventory = View only (default) | Inventory = View only (default) | Inventory = View only (default Off) |
| Inventory → History tab, item's recent changes; batch page → Stock changes | ✅ | Inventory history = View only (default Off; given by the superadmin) | Inventory history = View only (default Off; given by the superadmin or a GM who has it) | ❌ never |
| Set stock by hand | ❌ never (production items) | ❌ never | ❌ never | ❌ never |
| Workstation → Orders (list, order page) | ✅ | Orders ≥ View only (default Record) | Orders ≥ View only (default Record) | Orders ≥ View only (default Off) |
| Create orders, Start delivery, Mark delivered (incl. returns) | ✅ | Orders = Record (default) | Orders = Record (default) | Orders = Record |
| Edit / cancel Created orders | ✅ | Order management = Full (default) | Order management = Full (default Off) | ❌ never |
| Review returns; order alerts (bell, Telegram) | ✅ | Order returns = Full (default) | Order returns = Full (default Off) | ❌ never |
| Header bell | ✅ | ✅ | ✅ (empty without plan or order returns access) | ✅ (always empty) |
| My profile → Telegram card | ✅ | ❌ | ❌ | ❌ |

"Suppliers = Full" etc. refers to the levels a general manager (for staff also their supervisor) sets on the Access tab (§10). "(default)" is the level a new account starts with.

This matrix depends **only on role and access levels**. A staff member's position (e.g. `Grill cook` or `អ្នកដឹកជញ្ជូន`) never changes it: two staff with the same levels see exactly the same menu and screens.
