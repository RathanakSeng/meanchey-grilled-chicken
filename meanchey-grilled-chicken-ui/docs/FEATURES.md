# UI Features — Phase 1

What the Mean Chey Grilled Chicken UI (មាន់អាំងមានជ័យ) offers today. One React app serves both the **PC dashboard** and the **Telegram Mini App**.

Phase 1 covers sign-in, user management and access control (feature access levels), plus the **Workstation** features: **Suppliers**, **Customers**, **Production** (batches in three steps, with autosave), the **Production plan** (packaging plans between steps 2 and 3), **Inventory** (stock updated automatically by production), **Orders** and **Preparation** (satay sachets and packaging materials made ready from raw materials), with production, order and preparation alerts in the header bell and on Telegram, plus **Attendance** (GPS check-in / check-out from the Mini App, reminders, the day view and corrections).

> The UI hides what a user can't do, for a cleaner experience. **The API enforces every rule**, so hiding things in the UI is never the security boundary.

- [1. Two experiences, one app](#1-two-experiences-one-app)
- [2. Sign-in](#2-sign-in)
- [3. Forced password change](#3-forced-password-change)
- [4. App shell and navigation](#4-app-shell-and-navigation)
- [5. Home](#5-home)
- [6. Workstation (កន្លែងការងារ)](#6-workstation-កន្លែងការងារ)
- [7. Attendance (វត្តមាន)](#7-attendance-វត្តមាន)
- [8. Settings](#8-settings)
- [9. Users](#9-users)
- [10. User detail](#10-user-detail)
- [11. Access tab and Permissions (advanced)](#11-access-tab-and-permissions-advanced)
- [12. Audit log](#12-audit-log)
- [13. My profile](#13-my-profile)
- [14. Language (Khmer / English)](#14-language-khmer--english)
- [15. Error and status screens](#15-error-and-status-screens)
- [16. Screen access matrix](#16-screen-access-matrix)

---

## 1. Two experiences, one app

| | PC dashboard | Telegram Mini App |
|---|---|---|
| Opened from | Browser | The bot's **Open app** button or menu button (**បើកកម្មវិធី**), or the **Attendance** button (in `/start` for staff and supervisors, reminders and confirmations) straight to the check screen |
| Sign-in | Username + password | Automatic, using Telegram `initData` |
| Layout | Left sidebar + top bar | Top bar + bottom navigation, full-height, safe-area aware |
| Navigation | Sidebar: Home · Workstation · Attendance · Settings (with its sub-pages nested) | Bottom bar: Home · Workstation · Attendance · Settings |
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

The app is organized in three sections under Home:

```
Home                      everyone
├── Workstation           everyone          /workstation
│   ├── Suppliers         suppliers.view    /workstation/suppliers
│   ├── Customers         customers.view    /workstation/customers
│   ├── Production        production.view   /workstation/production  (batch: /workstation/production/:id?step=1|2|3)
│   ├── Production plan   production_plan.view  /workstation/production-plans  (plan: /workstation/production-plans/:batchId)
│   ├── Inventory         inventory.view    /workstation/inventory  (?tab=history)
│   ├── Orders            orders.view       /workstation/orders  (new: /new; order: /:id; edit: /:id/edit)
│   └── Preparation       preparation.view  /workstation/preparations  (preparation: /:id)
├── Attendance            staff, supervisors, attendance.view / .scheduling   /attendance
│   ├── (check screen)    staff, supervisors /attendance/check
│   ├── My attendance     staff, supervisors /attendance/me  (?year&month)
│   ├── Today             attendance.view   /attendance/today  (?date&workplace&status&role&q)
│   ├── Scheduling        attendance.view or .scheduling   /attendance/scheduling (workplaces) → /:workplaceId  (?m)
│   └── (employee)        attendance.view   /attendance/employees/:id  (?year&month; from Today)
└── Settings              everyone          /settings
    ├── Users             users.view        /settings/users
    ├── Audit log         superadmin; GM if allowed (audit.view)   /settings/audit-logs
    ├── User limits       superadmin        /settings/user-limits
    ├── Workplaces        attendance.workplace_view, _update or _manage
    │                       /settings/attendance/workplaces  (?archived=1; new: /new; one: /:id)
    └── My profile        everyone          /settings/profile
```

- **Each item appears only when the user is allowed to open it.** The rules are unchanged from before: Users needs `users.view`, and Audit log needs `audit.view` (the superadmin always; a general manager only when the superadmin allows it).
- **Settings is always shown,** because everyone can open My profile.
- **Workstation is always shown,** even when none of its pages are visible, so its hub can explain that nothing is available yet.
- **Staff** see Home, Workstation and Settings. Workstation shows the "no access yet" message and Settings only My profile, which follows from the permissions with no special handling. Once a general manager (or their supervisor) sets e.g. Suppliers to *View only* on the Access tab, Suppliers appears for that staff member.
- **Desktop sidebar:** Home, Workstation and Settings.
  - While you're anywhere under Workstation or Settings, that section's visible sub-pages are listed indented below it.
  - The current page and its section are highlighted.
- **Attendance is shown to tracked employees and to holders of `attendance.view`** (a rule with `anyOf`: role *or* permission); a general manager without Attendance access doesn't see it.
- **Mobile / Telegram bottom bar:** Home · Workstation · Attendance · Settings (Attendance only when visible). Settings stays highlighted on every Settings page.
- **Back buttons,** both in-page and Telegram's native one, go to the **parent screen**, not the browser history. For example: user details → Users → Settings → Home, Suppliers → Workstation → Home, and a production batch → Production → Workstation → Home, and a plan → Production plan → Workstation → Home. A deep link opened straight into the Mini App therefore still has a sensible way back.
- **Header:** language switcher (ខ្មែរ / EN), the **notification bell** (§6.4) and an avatar menu.
- **Badges:** *Production plan* shows the number of plans waiting to be set, in the sidebar and on its Workstation card (only for people who can see plans).
- **Avatar menu:** name, role, Telegram username, **My profile** and **Log out**.
- **Permission changes show up quickly.** Menus refresh when Home, Workstation or Settings is opened and the cached permissions are more than a minute old. They also refresh whenever the server answers "no permission", "wrong role" or "out of scope".
- **Old links keep working.** Old addresses (`/users/…`, `/audit-logs`, `/profile`) redirect to their new place under `/settings`, keeping the rest of the address, for example `/users/<id>?tab=permissions`.
## 5. Home

- A welcome banner with the user's name and role badge (plus position for staff).
- **Connect Telegram:** a GM, supervisor or staff member who gets alerts or attendance reminders (`me.telegram_alerts`: an alert permission, or tracked for attendance) while their Telegram isn't linked sees a blue banner: *"Connect Telegram to get alerts — open the bot and press Start."* / *"ភ្ជាប់ Telegram ដើម្បីទទួលការជូនដំណឹង — បើកបូត ហើយចុច Start។"* with **Open the bot** (`https://t.me/<bot>`, from `GET /me/telegram-bot`; hidden when the bot isn't configured). Pressing Start links the account by username; the banner goes away when the window gets focus again. **✕** dismisses it on this device. Not shown to the superadmin (it links from its profile, §12).
- **Tracked employees** (staff, supervisors): the **Attendance** card first, with the one action now (§7.2).
- Large tiles, one per section the user sees, each with an icon, a title and a one-line description. They sit side by side on desktop and stack on mobile:
  - **Workstation (កន្លែងការងារ):** your daily work: suppliers, customers and more;
  - **Attendance (វត្តមាន):** check in and out, and see attendance;
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
| Preparation | holders of `preparation.view` |

With no visible cards (staff by default) it shows *"You don't have access to any workstation features yet"* with a hint to ask a manager.

### 6.1 Suppliers and customers

**Paths:** `/workstation/suppliers`, `/workstation/customers`. **Who can open them:** users whose Suppliers / Customers access is *View only* or *Full access* (§11): by default general managers and supervisors; staff once a general manager turns it on. Both pages work the same way.

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

**Paths:** `/workstation/production` (list) and `/workstation/production/<id>?step=1|2|3` (a batch). **Who can open them:** Production access *View only* or higher (§11): by default general managers and supervisors; staff once a general manager turns it on.

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

**Step 3: Standardize.** While the plan isn't confirmed, step 3 shows *"Waiting for the packaging plan"* (with **Open plan** for plan holders) instead of the form; the API refuses saves too. Then: **4-Piece Packs** (កញ្ចប់ ៤ ដុំ, *1 × 4-piece = 2 wings + 2 thighs*) and **2-Piece Packs** (កញ្ចប់ ២ ដុំ, *1 × 2-piece = 1 wing + 1 thigh*) with a live breakdown, rejected wings and thighs, a **Plan vs actual** panel (planned and actual per pack size, ⚠ where they differ), and a **balance meter** per piece type (*"Wings: 3 left to assign"*, *"2 too many"*, *All assigned*). For each by-product: the produced kg, **carry forward** (យកទៅបន្ត) and **rejected** (ខូច/មិនប្រើ) inputs, and a per-row indicator. **Prefilled when the form opens** (every value can be edited): empty pack counts take the confirmed plan's 4-piece / 2-piece counts, rejected wings and thighs 0, and each by-product with nothing typed yet carries forward its whole produced kg with 0 rejected; the prefill is saved like typing (autosave), and fields that already have a value are never touched. The comment is optional, **unless the packs differ from the plan**: then an amber notice says *"Different from the plan — add a comment."*, the comment becomes required (*Comment \**) and Finish stays disabled (*"Comment required: packs differ from the plan."*). The API enforces it too. The step 3 summary shows the plan vs actual panel.

**Satay sachets (step 3).** Every pack gets one matching sachet: **4-Piece Pack → 4-piece satay sachet**, **2-Piece Pack → 2-piece satay sachet**. Under the packs, **Satay sachets (4-piece)** and **Satay sachets (2-piece)** (numeric keypad) are prefilled with the pack counts and follow them live while on auto (a small *auto* badge, *"One per pack"*). Typing a count keeps it (even when the packs change) and shows **Reset to auto**; the choice is saved on the server, so it's the same on every device. Next to each: *"In stock: 120"* (with Production Record, while step 3 of a counted batch is a draft), red when the count is higher. When a count differs from its pack count an amber notice says *"Sachets differ from packs — explain in the comment"* and the **same comment** becomes required (one comment for the plan and the sachets; the blocker list says *"Comment required: satay sachets differ from the packs."*). Finish is also blocked by *"Not enough satay sachets (4-piece): 40 in stock, 70 needed"*. Finishing step 3 takes the sachets out of inventory (oldest preparation first); reopening puts them back. The step 3 summary shows the sachets used per size, with the difference from the packs (*"(+2 vs packs)"*). Batches from before inventory record the counts but never touch the stock.

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

**Paths:** `/workstation/production-plans` (list) and `/workstation/production-plans/<batch id>` (a plan). **Who can open them:** Production plan access *View only* or *Full access* (§11): by default general managers; supervisors once a general manager turns it on; never staff. Plans are created by finishing step 2; step 3 can't start until the plan is confirmed.

**List:** status chips **Waiting for plan** (default, with the count) · **Confirmed** · **Completed** · **All**, and a search (batch code or supplier), kept in the address. Each row / card: batch code, production date, supplier, chickens, wings / thighs, the planned packs and a status badge. Cancelled batches never appear.

**Plan page:**

- **Header:** code, status, production date and supplier, and **Open batch**.
- **Processed (step 2)**, read-only: wings and thighs (kg and pieces), each by-product (kg, catalog names), marinade (g), number of chickens.
- **Packaging plan:** with *Full access* and while it can change: **4-Piece Packs** and **2-Piece Packs** (numeric keypad), an optional note, and a live meter *"Uses 296 of 300 wings · 296 of 300 thighs"* that turns red when the plan needs more pieces than were produced (Save and Confirm are then disabled; the API checks the same rule). **Save** keeps the values; **Confirm plan** asks *"Confirm the plan? … Step 3 can start once the plan is confirmed."*. A confirmed plan shows *Confirmed by … · time* and stays editable with **Save** (it stays confirmed) until step 3 is finished.
- **Satay sachets** (information only), under the plan: *"Needs 70 × 4-piece and 30 × 2-piece satay sachets · in stock 40 / 50"*, following the typed counts while editing. When the stock won't cover the plan it turns red with *"Prepare more sachets before packing"*; confirming is still allowed (step 3 Finish is where stock is enforced). Hidden until both counts are saved, for batches from before inventory, and once step 3 is finished.
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

**Telegram delivery note:** under the time, an item that didn't reach Telegram says so in small amber text: *"Not sent to Telegram (not linked)"* (`telegram_status = not_linked`) or *"Not sent to Telegram"* (`failed`).

| 🧂 | A preparation finished (§6.7) | *"PP-…: preparation finished — 40 satay sachets (2-piece), 25 (4-piece) | Skewer 2.000 kg."* ("again" after a reopen) | the preparation |
| 🚚 ✅ ↩️ 📦 | An order out for delivery, delivered, returned, return reviewed (§6.6) | e.g. *"OR-…: Dara Shop returned items — 2 × 4-Piece Packs. Review the return."* and the reason | the order |

**Who gets them:** production alerts go to everyone with Production plan access, preparation alerts to everyone with **Preparation management**, order alerts to everyone with **Order returns** (general managers, supervisors given access, and the system account), also on **Telegram** when their Telegram account is linked, with an **Open plan** / **Open batch** / **Open order** button into the Mini App. Staff get none.

### 6.5 Inventory (ស្តុក)

**Path:** `/workstation/inventory`: main tabs **Stock** (ស្តុក, `?tab=stock&section=raw|processed|packed|prepared|wasted`) and **History** (ប្រវត្តិ, `?tab=history`). **Who can open it:** `inventory.view` (GM and supervisors by default; staff when given *View only*). Lazy-loaded.

**Production items are read-only.** Every production item changes only through production (Finish, reopen, cancel) and orders (Start delivery, return review, §6.6); nobody sets their stock by hand. **Materials** (string, skewers, stickers, sauces, bags…) are the exception: see *Materials* below. **History** (every movement) needs **Inventory history** (`inventory.history`), which is off by default: without it there is no tab bar and Stock shows directly, item sheets show no recent changes, and batch pages show no Stock changes.

Stock updates **automatically** as production steps are finished; reopening a step or cancelling a batch undoes what it did. Nothing can go below zero.

**Stock tab**: four sub-tabs, each a grid of item cards, like a menu of products.

- **Sub-tabs:** **Raw** (វត្ថុធាតុដើម: Chicken, then the materials) · **Processed** (ផលិត: Wings, Thighs, Gizzard, Liver, Heart, Head) · **Packed** (វេចខ្ចប់: 4-Piece Packs, 2-Piece Packs, Gizzard, Liver, Heart, Head) · **Prepared** (រៀបចំរួច: Satay sachets 2-piece and 4-piece, then each packaging material's prepared stock, §6.7) · **Wasted** (ខូចខាត: Wings, Thighs, 4-Piece Packs, 2-Piece Packs, by-products). Which tab an item belongs to comes from the API, so a new by-product appears in the right one on its own.
- **Pill bar**, lighter than the main tabs (pills on a grey track, no underline): full width with equal pills on phones and in the Mini App (scrolls sideways if a label doesn't fit), compact and left-aligned from tablets. The selected Wasted pill is muted red, so it's never mistaken for stock.
- **Stock badge** on each pill: how many items in that tab have stock (count or kg above 0); no badge at 0 or while loading. It updates in place when production changes stock.
- The selected sub-tab is in the URL (`?tab=stock&section=processed`; default **Raw**), so refresh, Back (e.g. after opening a batch from an item's history) and shared links keep it. Switching to History and back keeps it too.
- A sub-tab without any items (only possible for a future section) shows a short empty state.
- **Grid:** 2 cards per row on phones and in the Mini App, 3 from tablets, 4 on laptops, 6 on wide screens; every card in a row has the same height.
- **Card:** a picture; a small **ខូចខាត / Wasted** corner badge in the Wasted tab only (the sub-tab already says processed / packed); the **short name** (*ថ្លើមមាន់*, not *ថ្លើមមាន់ (ផលិត)*: the sub-tab says it), up to 2 lines; the **big number** (the count for Chicken, Wings, Thighs and Packs; the kg with its unit for by-products, e.g. *12.500 គ.ក*); for items with both units the kg under the count (*"210.000 គ.ក"*, **"≈"** with the tooltip *"Estimated from the batch's average weight"* for wasted pieces); and the last change (*"Updated 2 h ago"*, *"No changes yet"*). No action button on production items: they aren't changed by hand.
- **Zero** balances: the card is dimmed (grey number and picture), still tappable.
- Wasted cards show the stock picture in grey.
- **Day one:** a note above the sub-tabs says *"Stock starts at zero. It updates automatically as production steps are finished."* while every balance is 0.
- While loading: the sub-tabs (without badges) and grey placeholder cards in the grid.
- **Tap a card** → the **item sheet** (drawer on PC, bottom sheet on phones): big picture, full name (e.g. *Liver (processed)*), its sub-tab as a label (red for Wasted), balance (count and / or kg), last change, and:
  - **From production** (ពីផលិតកម្ម), for everyone with Inventory: one row per batch that currently contributes, oldest first: the batch code (opens the batch at that step) · the last step that still contributes, and its count and / or kg (**"≈"** when estimated); then a **Total** line equal to the balance. Nothing to show: *"No stock from production right now."* Example: after the 50-chicken batch finishes step 2 it leaves Chicken and appears under Wings and Thighs.
  - With **Inventory history** only: the item's **last 20 changes** (time, + green / − red, new balance, source: the batch code linking to the batch · step, *"Reversed: reopen / cancelled"*, by whom) and **See full history**, which opens the History tab filtered by that item (the sub-tab is kept for coming back).
- Numbers use one rule everywhere (`lib/quantity.ts`, the same as the API): counts as whole numbers with thousands separators, kg always with 3 decimals (*1.250 គ.ក*), g with 1 (*2,350.0 ក្រាម*), m² with 2 (*12.50 ម៉ែត្រការ៉េ*; the cards and the unit chips write the short *12.50 m²*, because the Khmer word is long).

**Materials (in Raw)**

- **Cards:** after Chicken, the active materials sorted by name in the UI language (defaults: String, Skewer, four Stickers (2- and 4-piece packs, each in kg *· គ.ក* and in m² *· ម៉ែត្រការ៉េ*), Marinade sauce, Satay sauce, Zip bags 7 for 2- and 4-piece packs, Vacuum bag). Picture, first that exists: the **uploaded icon**, the material's **own illustration** (the eleven defaults: a coil of string, a bundle of skewers, round amber stickers with a *2* / *4* badge (kg) and a **teal roll of label stock with its sheet unrolled** and the same badge (m²), a sauce bottle for the marinade, a satay bowl, zip bags with *2* / *4*, a flat vacuum bag), else a generic icon by unit (a scale for kg / g, a grid for m², a number tag for counted ones). Then the balance with its unit and a soft orange **+ បន្ថែម / Add** button with **Inventory Record** (`inventory.materials_stock`). Marinade sauce has a small **ប្រើដោយផលិតកម្ម / Used by production** label.
- **Add sheet** (from the card or the item sheet): the quantity (numeric keypad for counts, decimal for kg / g / m²; a comma works too), quick chips that add up — count **+1 +5 +10**, kg **+0.5 +1 +5**, g **+100 +500 +1000**, m² **+0.5 +1 +5** (shown *+0.50 +1.00 +5.00*) — the precision hint, *"In stock: …"* and the **new balance** preview. Too many decimals or 0: a red hint and Save stays disabled.
- **Item sheet** of a material: balance, **Add** and **Remove** (Inventory Record; Remove asks for the quantity and a required **reason**, shows the new balance, refuses more than is in stock); **⋮ Edit / Archive** with **Inventory materials** (`inventory.materials_manage`). Marinade sauce has no Archive and shows *"Production step 2 takes its marinade from this material. It can be renamed, but not archived."* No *From production* section; recent changes only with Inventory history.
- **Add material** (solid orange button in the header of Raw, with Inventory materials) and **Edit**: Khmer name, English name, unit (**kg · g · m² · count**: four equal options (*គ.ក · ក្រាម · ម៉ែត្រការ៉េ · ចំនួន*) that always fit the sheet: 2 × 2 on phones and in the Mini App, one row from the `sm` breakpoint, in both languages; hint *"Counted in pieces, or measured in kg, g or m²."*), and an optional **Icon** (រូបតំណាង): a preview, **Upload** / **Change** and **Remove** (PNG, JPEG or WebP up to 1 MB; the server stores it as a square). Editing uploads or removes it right away; a new material's icon is uploaded right after the material is created (if that upload fails the material is saved anyway and the sheet stays open on it, with *"The material was saved, but its icon wasn't uploaded."*). Removing an upload brings back the default picture. Not an image → *"The icon must be a PNG, JPEG or WebP image."*; too big → *"…at most 1 MB."* The unit explains: *kg ↔ g converts the stock automatically; switching to or from count or m² is only possible before the first stock entry* (count and m² are disabled with that tooltip once the material has moved, and kg / g too when the material is in m²; Marinade sauce can only be kg or g). Saving kg → g converts the balance (e.g. 3.750 kg → 3,750.0 g) and the history shows *"Unit changed"* with both values; older rows keep their unit. A name already used → *"Another material already has this name."*
- **Archive:** a confirmation that warns when stock is left (*"There is still 3,750.0 g in stock…"*). Archived materials leave Raw. **Show archived** (managers; Khmer *បង្ហាញសម្ភារៈដែលបានលុបចោល*) lists them dimmed under *Archived materials* with an *Archived* badge and **Restore**. In Khmer, archive is **លុបចោល** and restore **ស្ដារវិញ** everywhere (menu, confirmation *"លុបចោលសម្ភារៈនេះ? ស្តុក និងប្រវត្តិនៅតែរក្សាទុក ហើយអាចស្ដារវិញបាន។"*, badge *បានលុបចោល*, audit labels, errors). The audit log shows icon changes as *Icon changed* / *Icon removed*.
- **History:** *Added*, *Removed — reason*, *Unit changed*, and step 2's marinade (*PR-… · Processing −350.0 g*); the type filter has the three material types.

**Prepared (រៀបចំរួច)**

- **Cards:** the satay sachets (a sachet picture with a *2* / *4* badge) and one card per packaging material (String, Skewer, Stickers, Vacuum bag, materials created in the app): the material's own picture (uploaded icon or bundled picture) with a small green **រៀបចំរួច / Prepared** badge, so it's never mistaken for the raw stock; the amount in the material's unit. An archived material's prepared card stays while it still has stock. **No Add / Remove / Edit** on them: only preparations change them.
- **Item sheet:** **From preparations** (ពីការរៀបចំ) instead of From production: one row per preparation that currently adds to it (its code, linking to the preparation, and its prepared date) with the amount, then a Total equal to the balance; *"Nothing from preparations right now."* when empty. Recent changes with Inventory history as usual.
- History rows: *"Preparation PP-…"* (links to it) or *"Reversed: reopen / cancelled · PP-…"*; prepared items read *"Prepared: Skewer"*. The area filter has **Prepared**, the type filter **Preparation**.

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
- **Step 2 marinade:** under the marinade field, *"Available: 2,350.0 g"* (with Production Record, while step 2 is a draft). When the entered amount is higher it turns red and Finish is blocked with *"Not enough marinade sauce in stock"*. Finishing step 2 takes the marinade out of Marinade sauce; reopening or cancelling puts it back. The Stock changes card lists it under step 2. Likewise step 3 lists the satay sachets it used (one row per size).
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
- **Status chips:** All · Created · Delivering · Return pending · Completed (success, partly or fully returned) · Cancelled. **Search** (order code, customer name, phone or location; *"ស្វែងរកលេខកូដ អតិថិជន លេខទូរស័ព្ទ ឬទីតាំង"*; `012 345` finds 012 345 678), **customer type** (*Saved and direct* · **Saved customers** (*អតិថិជនក្នុងប្រព័ន្ធ*) · **Direct orders** (*ការបញ្ជាទិញផ្ទាល់*)), **Customer** (for people who record or edit orders; hidden with Direct orders, which have no saved customer) and a **delivery date** range. Everything is in the URL (`?status=&type=&customer=&from=&to=&q=&page=`), 20 per page.
- Phones: a card per order (code, customer, status badge, delivery date · driver, ▢ white / ■ black box counts, plus the plastic / delivery bags when the order has some). Desktop: a table with the same columns. The customer is the saved customer's name, or a blue **Direct order** badge with the phone. **New order** with `orders.create`.

**Order form** (create; edit while Created with `orders.update`)

- **Customer**: two equal options, **អតិថិជនក្នុងប្រព័ន្ធ / Saved customer** · **ការបញ្ជាទិញផ្ទាល់ / Direct order** (full width, fits phones and the Mini App).
  - **Saved customer:** the picker (active customers, search by name or phone; no Customers access needed); the chosen customer's phone and location are shown under the name, read-only (they come from Customers).
  - **Direct order:** **Phone** (required; the phone keypad on mobile) and **Location (optional)**, for this order only (*"For this order only: nothing is added to Customers."*). No name: it's shown as *Direct order*. Phone checks match the API: empty → *"Enter the phone number."*; not 8–15 digits (optionally starting with +) → the usual phone message, also when the server refuses it.
  - Switching between the two keeps what was entered in the other one until the order is saved; only the selected one is sent. Editing a Created order can switch it either way.
- **Delivery date** (today), **Driver** (optional: active staff and supervisors), **Note**.
- **Boxes builder:** next to **Boxes**, **+ Add box ▾** opens a menu of the box types, each with its marker: *White box* □, *Black box* ■, *Plastic bag* (dashed outline), *Delivery bag* (half filled). Picking one adds a card at the bottom (*Box 3 · Plastic bag*) and scrolls to it; tapping outside or Esc closes the menu without adding. Each card has item lines: the item (4-Piece Packs, 2-Piece Packs, packed by-products, each with the stock available, e.g. *"4-Piece Packs (12 in stock)"*; an item already in that box is disabled) and the quantity (whole numbers for packs, kg with up to 3 decimals for by-products), **×** to remove a line, **Add item**; box actions **Duplicate** (inserted after it) and **Remove**.
- **Live summary:** per container, in the order white boxes, black boxes, plastic bags, delivery bags (*White boxes: 2* — 4-Piece Packs 5, 2-Piece Packs 1, Liver (packed) 0.150 kg), then the **grand total**; an amber line when a total is above the stock (*"Only 12 × 4-Piece Packs in stock."*). Sticky beside the form on desktop; on phones a bar at the bottom (*Summary · Boxes: 3*, with ⚠ when short) that opens it, with the Save button.
- **Checks before saving** (the same as the API's): a customer (or a direct order's phone), a date, at least one box, at least one item per box, an item and a valid quantity on every line, an item at most once per box. Mistakes are outlined in red with a short message, and *"Check the highlighted fields."* above Save.
- Saving opens the order. A stock warning doesn't block saving; stock is only taken at Start delivery. If someone else changed the order meanwhile, the form reloads it with a notice.

**Order page**

- **Header:** code, status badge, customer (name, or the **Direct order** badge with the phone); **ទាញយកប័ណ្ណដឹកជញ្ជូន ▾ / Export Delivery Note ▾** with **PDF** or **Excel** (only with `orders.export_delivery_note`, see *Delivery note* below); **⋮** with **Send to my Telegram**, **Edit** (`orders.update`) and **Cancel order** (`orders.cancel`) while Created.
- **Details:** customer (name, or the **Direct order** badge; phone as a tap-to-call link; location if any). These are the order's own copy: they follow edits of the customer while the order is Created and stay as they were when delivery started afterwards (a renamed customer doesn't change delivered orders); delivery date, driver, note, and once a PDF was exported or sent *"PDF exported 2× (downloads and Telegram)"*. While Created with too little stock: an amber list (*"Only 12 × 4-Piece Packs in stock."*).
- **Main action** by status (a full-width button under the header on phones):
  - Created (`orders.create`): **Start delivery** → a confirmation (*"The 3 boxes for Dara Shop leave stock now (oldest batches first). This can't be undone."*); a stock refusal names each item (*"Not enough 4-Piece Packs in stock: 7 available, 9 needed."*).
  - Delivering (`orders.create`): **Mark delivered** → a sheet: **Everything accepted**, or **Some items returned** with a quantity per item (the delivered amount shown next to it, at most that) and a required **reason**.
  - Return pending (`orders.review_returns`): **Review return** → a sheet: the reason, then per item what came back with **Back to stock** and **Wasted** (they must add up, shown in red until they do); **All to stock** / **All wasted** fill every item. Without the permission: *"Waiting for a manager to review the returned items."*
- **Status** timeline: Created → Out for delivery → Delivered (*Delivered, items returned*) → Return reviewed, or Created → Cancelled, each with its time and who did it ("System" for the system account).
- **Summary** (per colour and grand total), **Boxes** (each box with its lines), and after a return **Returns** (delivered / returned and, once reviewed, back to stock in green and wasted in red, with the reason).
- **Cancel order:** a sheet with the reason pre-filled *"Customer cancelled"* (required).
- **Conflicts:** if someone else moved the order on, the page shows the current order with *"Someone else changed this order. It has been reloaded; check it and try again."*

**Delivery note (ប័ណ្ណដឹកជញ្ជូន)** — everyone who can open the order, any status (Created onward, Cancelled too). The API makes an 80 mm receipt PDF (API FEATURES §19.6): business info and logo, the title (no COPY mark: every print looks the same), CANCELLED on cancelled orders, customer / delivery date (no driver), white boxes, black boxes, plastic bags then delivery bags with their lines (no subtotals or grand total), returns (when there are any), the note, **Prepared by** with the name, **Received by** with a signature line and the delivery date filled in, and the Business info footer note (no QR code). Khmer with English under each label, black and white only.

- **Export Delivery Note ▾** (header button, only for people holding **Export delivery note**: the GM and the superadmin by default; supervisors and staff once granted, see *Access*) opens a menu below it: **PDF** (*ឯកសារ PDF*) and **Excel**. The button stays compact (icon and ▾ only under 400 px) and shows a spinner while exporting; *"Delivery note exported as PDF."* / *"…as Excel."*
- **PDF:** the API's delivery note (`GET /orders/{id}/document.pdf`, the same PDF Send to my Telegram sends), saved as `<order no.>.pdf`: in the **Telegram Mini App** through the system share sheet when the WebView can share files, otherwise the normal download. It is counted (the export count refreshes); API errors are translated.
- **Excel:** builds the note in the browser from the template `public/templates/delivery_note_template.xlsx` and downloads `DeliveryNote_<customer>_<order no.>_<YYYY-MM-DD>.xlsx` (Khmer letters kept; characters not allowed in file names replaced). Nothing is generated or stored on the server; the only API call is `GET /orders/delivery-note/supplier` (the supplier block). The sheet gets: **Supplier** (Business info name, phone and address, in the UI language) · **Customer** (the order's own copy: name or *Direct order*, phone, location over two lines when long) · **Date** (the delivery date) · one row per item of the order's total (running number, item name, and its **total quantity** in the Unit column: *12* for counted items, *1.250 kg* for by-products); Item Code, Picture, Remark, Ref. Invoice and Ref. PO stay blank, ISSUED BY / CONFIRMED BY stay as in the template. **Fonts:** every cell with text, the template's labels included, is checked for Khmer letters: Khmer text (also mixed Khmer + English) gets **Khmer OS Content**, everything else (English, numbers, dates, phone numbers) **Trebuchet MS**; everything the export writes (supplier, customer, date, item numbers, names and quantities) is **size 11**; the template's own labels keep their size, bold and colour (install both fonts on the computer that opens the file). More than two items insert rows styled like the first item row, so the signature blocks move down with their formatting. The button shows a spinner while it builds; errors (template not loaded, no business name yet, no customer details, no items, API errors) are translated. In the **Telegram Mini App** the file is offered through the system share sheet when the WebView supports sharing files, otherwise through the normal download link. The Excel library (ExcelJS) loads only when the button is pressed.
- **Send to my Telegram** (unchanged): the bot sends the PDF to the person's own Telegram chat; *"Sent to your Telegram chat."* It is always in the ⋮ menu (there's no PDF print button any more). Errors are translated: not linked → *"Your Telegram account isn't linked yet. Open the app once from the bot in Telegram (the Open app button), then try again."*; bot not configured; Telegram couldn't deliver it (blocked bot).
- Every PDF export or send is counted; the document itself has no COPY mark. The order shows *"Delivery note: PDF exported 3× (downloads and Telegram)"* (*"បាននាំចេញ PDF 3 ដង"*), refreshed after each one. Excel exports aren't counted.

**Elsewhere**

- **Inventory:** two new **Wasted** cards, 4-Piece Packs and 2-Piece Packs (packs returned damaged). The item sheet's *From production* breakdown already reflects orders (packs leave the oldest batches first; returns go back to theirs). History (with Inventory history) shows **Order OR-… · from PR-…** and **Return OR-… · to PR-…** rows linking to the order and the batch, and the Type filter has Order and Return.
- **Production batch page:** reopening or cancelling a batch whose packs already left in orders is refused: *"4-Piece Packs from this batch were already delivered in OR-20261003-001 — can't reopen or cancel it."*
- **Bell and Telegram** (holders of Order returns): 🚚 *"OR-…: for Dara Shop is out for delivery — 2 white boxes, 1 plastic bag."* (only the containers it has) · ✅ *"…delivered to Dara Shop, everything accepted."* · ↩️ *"…Dara Shop returned items — 2 × 4-Piece Packs. Review the return."* (with the reason) · 📦 *"…return reviewed — Partly returned (1 × 4-Piece Packs to stock, 1 × 4-Piece Packs wasted)."* Each opens the order. A direct order reads *"Direct order · 012 345 678"* (*"ការបញ្ជាទិញផ្ទាល់ · 012 345 678"*) instead of a name, here, in the Start delivery confirmation, on the delivery note and in the Telegram caption.
- **Audit log:** Order created / edited / cancelled (reason) / out for delivery / delivered (*Everything accepted* or *Items returned* with the reason) / return reviewed (partly / fully) / **Delivery note printed** (*PDF #2*: which export it was, *Downloaded / printed* or *Sent to Telegram*), with the order code linking to the order; record type **Order** in the filter. *Order edited* lists the changed fields: customer, customer type (*Saved customer → Direct order*), phone, location (old → new), delivery date, driver, note, and *Boxes*.

### 6.7 Preparation (ការរៀបចំ)

**Paths:** `/workstation/preparations` (list) and `/workstation/preparations/<id>` (a preparation). **Who can open them:** `preparation.view` (Preparation *View only* or *Record*: GM and supervisors by default; staff when given it). Lazy-loaded (one chunk per page). Menu icon: beaker.

Raw materials made **ready to use**. **Not production step 3 (Standardize)**: preparations only convert materials. A **preparation** (code `PP-YYYYMMDD-NNN`) has one type:

- **ធ្វើសាតេកញ្ចប់ / Make satay sachets**: satay sauce and zip bags 7 → satay sachets, a line per pack size (2-piece and / or 4-piece).
- **រៀបចំសម្ភារៈវេចខ្ចប់ / Prepare packaging materials**: skewers, string, stickers, bags… moved **1:1** from Raw to Prepared, a line per material.

**List**

- **Figures:** Drafts · Finished this month · Sachets (2-piece) this month · Sachets (4-piece) this month (Cambodia calendar), 2 × 2 on phones.
- **Filters** (in the URL: `?type=&status=&from=&to=&q=&cancelled=1&page=`): type, status (*Draft and finished* · Draft · Finished), a **Date** range (the prepared date, or the day it was started while not finished), search (code or material name), and **Show cancelled** (cancelled preparations are left out otherwise). 20 per page, newest first.
- Rows (table on PCs, cards on phones): code, type badge (orange *Satay sachets*, blue *Packaging materials*), what it makes (*"40 × Satay sachets (2-piece packs)"*, *"Skewer 2.000 kg"*), status badge (Draft amber, Finished green, Cancelled grey) and the prepared date (cards: *"Prepared 6 Oct"* / *"Started 6 Oct"*).
- **New preparation** (`preparation.create`): a sheet with **two big option cards** (one per type, with a picture and a one-line description); choosing one creates the draft and opens it.

**Preparation page**

- **Header:** the code, the type, status and type badges, the prepared date (*"Prepared 6 Oct 2026"*, or *"Started …"*), and **⋮** with **Reopen** (`preparation.update`, finished ones: a confirmation says the stock is put back) and **Cancel preparation** (`preparation.cancel`, draft or finished: a sheet with a required **reason**; a finished one's stock is put back first). Refusals (e.g. the outputs are no longer in stock) are translated per item.
- **Satay sachets form:** two line cards, *Satay sachets (2-piece packs)* and *(4-piece packs)*, each with its picture and an **Include** checkbox; an included line has **Satay sauce used (g)**, **Zip bag 7 used** (in that material's unit) and **Sachets made**, with *"Available: 1,500.0 g"* under each input, **red** when the entered amount is more (the two lines' sauce counts together).
- **Packaging materials form:** the hint *"Moves the same amount from Raw to Prepared."*, one card per material (picture, name, the quantity in its unit, *Available*, **×** to remove), and **Add material**: a sheet listing the preparable materials not in the list yet, each with its picture and balance.
- *"Finishing makes: …"* previews the outputs; a **Note**; *"The prepared date is recorded when you finish."*
- **Autosave** exactly like production steps (*Saving… / Saved just now / Offline — saved on this device / Couldn't save — retrying*): debounced, sent when the Mini App is hidden or closed, kept on the device, **Restore unsaved changes?**, and *Someone else saved … first* with **Keep my values** / **Use their version**.
- **Finish preparation** (sticky above the bottom bar on phones) with a confirmation (*"The stock moves now and the preparation is locked. Only a manager can reopen or cancel it."*); the list under the form says what's missing: *Add at least one line*, *Fill in every value (more than 0)*, *Not enough Satay sauce in stock*. The API checks everything again (a shortage → *"Not enough … in stock: … available, … needed."*).
- **Finished / cancelled:** a read-only summary: **Used** and **Made** (pictures, names, amounts), *Finished by … · time*, *Cancelled by … · time* and the note; a cancelled one shows its reason on top. With *View only*, a draft reads as a summary too (with a notice).

**Elsewhere:** Inventory's **Prepared** sub-tab (§6.5); the bell and Telegram (🧂, holders of Preparation management, §6.4); the audit log (*Preparation started / finished / reopened / cancelled*, the cancel reason, the sachets or materials of a Finish, linked to the preparation; record type **Preparation**). `prep_role` (which materials are preparable) isn't shown or editable yet.

## 7. Attendance (វត្តមាន)

**Path:** `/attendance`. **Who sees it:** tracked employees (active **staff and supervisors**) and holders of `attendance.view` or `attendance.scheduling`. A top-level section between Workstation and Settings (bottom bar: Home · Workstation · Attendance · Settings). Its hub shows the action card (tracked employees) and a card per page: **My attendance** (វត្តមានរបស់ខ្ញុំ, tracked employees), **Today** (`attendance.view`) and **Scheduling** (កាលវិភាគ, `attendance.view` or `attendance.scheduling`, §7.6).

### 7.1 Check screen (`/attendance/check`)

Opened by the Telegram reminders and confirmations, the **Attendance** button of the bot's `/start` message, the Home card and My attendance. Tracked employees only (lazy chunk with the map).

- **One action**, the API's `next_action`: *Check in — Morning shift* / *Check out — Morning shift* with *Open until 07:44*. With nothing to do (no window open, or a **day off**) it goes straight to the Attendance page, whose card says why. In the 12:30–12:59 overlap it shows the morning check-out first; the afternoon check-in is then the Attendance card's button. An `?action=` from an older link is ignored.
- **Before the start date / switched off:** instead of the form, a notice — *"Your attendance starts on 20 Oct 2026."* (the employee's `attendance_start_date`, `me/today` `starts_on`), or *"Attendance isn't required for you."* for a supervisor whose attendance is switched off (`tracked = false`). Nothing to confirm; the Mini App never asks for a location.
- **The location is read at once**, when the screen opens: Telegram's `LocationManager` (init, access request, `getLocation`) inside the Mini App when the client has it (Bot API 8.0+), otherwise `navigator.geolocation` with high accuracy (also when Telegram returns no accuracy). It **keeps listening for up to 20 seconds** and keeps the most accurate reading, so a rough first reading (indoors: ±96 m) gets better and the dot moves toward the real spot; it stops early at ±20 m. Meanwhile a grey line *"Improving GPS accuracy… ±96 m"* (*កំពុងធ្វើឱ្យ GPS ច្បាស់ជាងមុន…*). Denied → an explanation and **Open settings** (`LocationManager.openSettings()`, Telegram only); no GPS → *turn on location*.
- **Map** (Leaflet + OpenStreetMap): the employee's own workplace pin with its radius circle, the person's position with its accuracy circle. Status line: *"35 m from Mean Chey ✅"* or *"320 m away — you must be within 100 m ❌"*; when outside after listening, a hint with the accuracy: move near a door or window, then **Refresh location**.
- A big **Confirm check-in / check-out**, enabled as soon as the position is inside the radius while the window is open, **however rough the GPS reading** (no accuracy limit; also while it's still improving); **Refresh location**. The workplace without a position: the API's message instead of the map.
- **After a successful check** it goes straight to the **Attendance** page (`/attendance`, replacing the check screen in the history), whose card already shows the new check-in / check-out (and late minutes); no result screen and no Close button (the bot's Telegram confirmation still arrives). Refusals show the translated error (too far, too early, closed, …) and keep the form for a retry.

### 7.2 Home card

For tracked employees the first card on Home is **Attendance**. Its only action is the small header button; the rest is today's state.

**Before the start date** the card shows *"Your attendance starts on 20 Oct 2026."* in place of the shifts and the header button is disabled (*Check in · starts 20 Oct 2026*). A **supervisor whose attendance is switched off** (Settings → Users, §9) sees **no Attendance card** on Home or on the Attendance hub (`me.user.attendance_tracked = false`); the nav still lists *My attendance* for their past records.

- **Header button** (top right, compact on the title row, icon + label), from `next_action` in `me/today`:

  | `next_action` | Button |
  |---|---|
  | `check_in` / `check_out` | **ចុះវត្តមាន / Check in** or **ចុះចេញ / Check out**, enabled (brand orange), opens the check screen |
  | `none`, a window opens later today | the upcoming action's label, **disabled**, with *opens 12:30* (*បើកម៉ោង 12:30*) as a small second line |
  | `none`, nothing else today (the next opening is tomorrow's) | **ចុះវត្តមាន / Check in**, **disabled**, *Done for today* (*រួចរាល់សម្រាប់ថ្ងៃនេះ*) |
  | `none` on a **day off** (`day_off`) | **ចុះវត្តមាន / Check in**, **disabled**, *Day off* (*ថ្ងៃឈប់*) |

  There is no big action banner and no *My attendance* link (it is in the Attendance section).
- **On a day off** the shifts are replaced by an amber notice: *"Today — Holiday: Pchum Ben. No check-in today."* (or *Day off* for an untracked weekday) and *"Attendance resumes Thu 15 Oct, check-in opens at 06:30."*
- **Today's two shifts**, one row each: name and times, a badge and the details under it:
  - the shift whose window is open and still needs the employee: the phase badge (*កំពុងបើកចុះវត្តមាន* / *Check-in open*, *Check-out open*) with *until 11:44* or *check-out until 12:59*; while checking out is open, the check-in so far (*In 07:12 · late 12 min*);
  - otherwise the record's status (*Present*, *Late 12 min*, *Absent*) or the phase (*Not open yet*, *In progress*, …), and the recorded times (*In 07:12 · Out 12:03*, or *Forgot check-out*).
- **On time:** besides the one-minute refetch and the refetch on focus, `me/today` is refetched exactly when the next window opens (`next_opens_at`) or the open one closes (`closes_at`), so the button turns on and off on time without a reload.

### 7.3 My attendance (វត្តមានរបស់ខ្ញុំ, `/attendance/me`)

Tracked employees (it replaces *My day*, same address). From `GET /attendance/me/summary`.

- **Header:** the title, the workplace and its radius, and the same small **Check in / Check out** button as the Home card (§7.2: enabled in a window, disabled with *opens 12:30*, *Done for today* or *Day off*). On a day off the Home card's day-off notice is shown under the header.
- **Start date and untracked days:** days before the account's *attendance start date* are not listed (the year filter starts at it). Before it, the Home card's *"Your attendance starts on …"* notice is shown under the header and the button is disabled. Days inside a switched-off period are **greyed rows tagged *Not tracked* / មិនតាមដាន** and are left out of the KPIs, the chips and the month totals; a supervisor switched off sees the notice *"Attendance isn't required for you."* and keeps this page for their past records.
- **Period:** **Year** (from the year the account was created) and **Month** with a first option **ពេញមួយឆ្នាំ / Whole year**; no future months, none before the account existed. Default the current month; kept in the address (`?year=2026&month=10`; only `?year=2026` = the whole year). No day filter.
- **Four cards** (`KpiGrid`: 2 × 2 on phones, 4 in a row on desktop):

  | Card | Big | Under it |
  |---|---|---|
  | **មានវត្តមាន / Present** | *18 shifts* | *61 h 20 min*; *Morning 10 · Afternoon 8* |
  | **អវត្តមាន / Absent** | *2 shifts* | *7 h*; *Morning 1 · Afternoon 1* |
  | **មកយឺត / Late** | *4 times* | *1 h 05 min* |
  | **តុល្យភាពម៉ោង / Hours balance** | signed *−6 h 45 min* (red below 0, green above, neutral at 0) | *Extra +1 h 20 min · Missing −8 h 05 min* |

  Small neutral chips under them, each hidden at 0: *Early check-in: 6 · 1 h*, *Overtime: 3 · 20 min*, *Forgot check-out: 2*. Durations are hours and minutes (*ម៉ោង / នាទី* in Khmer), never decimals. The API's definitions: present minutes = scheduled − late + early + overtime; missing = absent + late minutes; extra = early + overtime; balance = extra − missing.
- **Daily table**, newest first, from the period start (or the account's creation) to today:
  - desktop: **Date** | **Morning shift**: In · Out · Status | **Afternoon shift**: In · Out · Status;
  - **In:** the time plus a small red *+12* (late minutes) or green *−20 early*; **Out:** the time plus a green *+25* (overtime), or *Forgot check-out*; an absent shift shows *—* with the **Absent** badge; a shift without a record (yet) shows *—*;
  - a corrected shift has a small *corrected* marker with the reason as its tooltip;
  - **holidays and days off** are marked in the day row (*Holiday: Pchum Ben* / *Day off*); without records the row shows only that mark (desktop: one cell across the shifts), and a kept corrected record is listed but, like the whole day, doesn't count in the cards or the month totals;
  - phones and the Mini App: one card per day (*Tue 13 Oct*) with two compact shift rows and the same tags.
- **Whole year:** grouped by month, collapsible, the newest month open; each header shows the month's present / absent counts and balance.
- No record at all in the period: *No attendance recorded in this period.*
- Month and weekday names come from the translations (`common.months`, `common.weekdaysShort`), since browsers often lack Khmer calendar names.

### 7.4 An employee's attendance (`/attendance/employees/:id`, `attendance.view`)

On **Today**, an employee's name opens their attendance: the same page (period, cards, chips, table) from `GET /attendance/users/{id}/summary`, with their name, role, position, workplace (and *Deactivated*) in the header and no check button. With `attendance.correct`, tapping a shift (a table cell or a phone row) opens the **Fix** sheet (§7.5) for that day and shift; saving refreshes the figures. Back goes to Today. Scope as on Today (a supervisor sees staff only); hidden accounts are *not found*.

### 7.5 Today (`/attendance/today`, `attendance.view`)

- **Header:** the long date (*Wednesday, 14 October 2026 · Today*), a day switcher (‹ date picker ›, never after today), **Today** and **Export CSV** (the primary orange button): downloads the rows the filters show (employee, role, position, workplace, and per shift status, in, out; UTF-8 with BOM so Excel reads Khmer), named `attendance-YYYY-MM-DD.csv`.
- **Filters** (one card): **Workplace** (shown when there is more than one), **Status** (present, late, absent, not yet, no record, forgot check-out), **Role**, a search box (name, position, Telegram username) and **Reset filters**; all in the address (`?date&workplace&status&role&q`).
- **Shift summary** (one card, a row per shift): name, phase badge, times, *N expected · M checked out* (and *forgot check-out*), a bar of on time / late / absent over the expected, *x of y attended*, and three **count chips** (on time, late, absent incl. no record) that apply that status filter when clicked (click again to clear; a zero is dashed). With a workplace chosen, its own shift times.
- **Day off** (the chosen workplace's, else the default's): an amber notice *"Holiday: Pchum Ben at Mean Chey: nobody is expected today."*; the figures count nobody, rows show *Day off* (a kept corrected record still shows), and **By workplace** shows *Day off* instead of the counts for a workplace that's off.
- **By workplace** (all workplaces, more than one): a table, a row per workplace with its own times per shift and the worst state as one chip (*1 absent*, else *1 late*, else *1 on time*) *of N*; clicking a row filters the page.
- **Employees** (table on desktop, cards on phones): one row per employee in scope (a supervisor sees staff only), the name opening their attendance (§7.4), with their workplace when several are shown, per shift (judged by that workplace's schedule) the status badge, *In 07:12 · Out 12:03* (or *Forgot check-out*), the distance at check-in, and a **Corrected** marker (the reason as its tooltip). **Exceptions first:** employees with an absent or missing record, then late / forgot check-out, then not yet, then those on time. Each cell shows the status badge, the scheduled times, *In … · Out …* or *No check-in*, and the Fix / Add record link.
- **Starts later** and **Not tracked** groups under the list (hidden when empty, filtered by the same role and search): employees whose attendance starts after that day (a badge with their start date, *from 20 Oct 2026*) and supervisors whose attendance is switched off. They are **not counted** in the figures or the expected total and are not rows of the list; only the name (opening their attendance, §7.4) and the role / position / workplace are shown.
- With `attendance.correct`: **Fix** on each shift cell (or **Add record** where there is none) opens a sheet with the current values (*Now recorded*, the shift's times that day at the employee's workplace), **Came to work / Absent**, the check-in time (present or late follows from it), the check-out (**Out** + its time, **Forgot**, **Not yet**) and a **required reason**. Saving refreshes the day and today's state.

### 7.6 Scheduling (កាលវិភាគ, `/attendance/scheduling`)

The single place for **tracked weekdays**, **holidays / occasions** and the **shift schedule and rules**, set per workplace (or for all at once). **Who sees it:** `attendance.view` (read-only) or `attendance.scheduling` (the edit controls). Lazy chunk.

- **Workplaces** (`/attendance/scheduling`): a card per active workplace (default first, *Default* badge) with its tracked days (*Mon–Sat*), both shift times and *Change planned from Sun 1 Nov 2026* when one is planned. Tapping a card opens that workplace's scheduling (`/attendance/scheduling/:workplaceId`, `?m=2026-11` the calendar month; the old `?w=id` links open it too). The list shows even with a single workplace.
- **A workplace's scheduling:** its name as the title, back to the list. Everything on it is that workplace's; there is no workplace selection.
- **Apply to all workplaces:** a checkbox next to **Save** (Tracked weekdays, Shift schedule) and in the Holiday sheet, unticked by default, reset after saving, hidden when there is only one workplace. Ticked, Tracked weekdays / Shift schedule confirm *"This also replaces the tracked weekdays of 2 other workplaces from Tue 1 Dec 2026."* and save for every workplace. Saving confirms with a line on top (*"Holiday saved. 3 attendance records were removed."*), closable.
- **Calendar:** the card header has **Add holiday** (`attendance.scheduling`; prefilled with today, or the 1st of the month shown) and a ⋮ menu with **Copy holidays from {last year}** into the shown month's year, for every workplace (confirmation says so; same day next year, 29 Feb → 28 Feb, Khmer holidays move so check the dates; the result reads *"5 holidays copied. 2 were already there."*). Then a plain month grid of this workplace's days, Monday first, month / year arrows and **Today**. Each cell (≥ 44 px, tappable): the day number; holiday names as text (truncated, full name on hover / long-press; on phones a dot, the list below names them); untracked weekdays greyed *Day off*; today outlined. Legend under the grid: *Holiday · Day off · Tracked*. No gradients, animations or decorative icons; high contrast.
- **Holidays of the month** under the grid (date range, name, days, workplaces, note) with **Edit** / **Delete** (`attendance.scheduling`).
- **Tap a day** (`attendance.scheduling`): a day with a holiday opens it; another opens **Add holiday** prefilled with that day. The **Holiday** sheet: name (Khmer, English), **From** / **To** (whole days, at most 31; the day count shown), note and ☐ **Apply to all workplaces** (*Workplaces added later are included too.*). Unticked, a new holiday is this workplace's only; unticking one that was for all makes it this workplace's only; one already shared by a few workplaces keeps them (*Also at: GDT*). Opening a holiday for all says *Shared with all workplaces: changes apply to every workplace.*; deleting it adds *This removes it for all workplaces.* (or *This removes it for Mean Chey, GDT.*). A holiday that includes today or earlier warns and asks: *"Attendance already recorded on these days will be removed (corrected records are kept)."* Deleting one with past days says their absences come back.
- **Tracked weekdays:** seven toggles Mon–Sun (Monday first), **Applies from** (today by default, never the past; *Until then the current settings stay.*), Apply to all workplaces, **Save**. Untracking today from today warns and asks: attendance already recorded today will be removed (with Apply to all, whenever today is left out).
- **Shift schedule and rules:** start / end of both shifts, check-in opens (min before), absent after (min after the start), check-out window, Telegram reminders, count early check-in / overtime as extra time, a **live preview** of each shift's windows (computed like the API), **Applies from**, Apply to all workplaces, **Save**; the API's problems (overlaps, windows outside the day, …) in plain words. A note: records already made keep their times; from today, new times apply to windows that haven't opened yet.
- **Upcoming changes** of this workplace: *From Sun 1 Nov 2026* and what changes (tracked days, shift times, rules), each with **Delete** (confirmation).
- Read-only (`attendance.view` only): the same page without Save, Add, Edit, Delete or Copy; calendar cells aren't tappable.
- After any change the scheduling, calendar and holiday queries refetch, and so do today's state, the day views, the summaries and the workplaces (their schedule summary).

### 7.7 Requests (សំណើ, `/attendance/requests`)

After a month ends, a tracked employee whose **missing time is at least 1 hour** sends **one request** for it: how it will be covered, by a **salary cut**, **unpaid extra work** or **both**. A reviewer approves, approves with changes or rejects. Fulfilment (payroll, the extra work) happens outside the app for now. **Who sees it:** tracked employees (their own) and holders of `attendance.requests_review` (Attendance requests, GM Full by default). The sub-tab sits under Attendance; for reviewers it carries the **pending count badge** (`pendingRequests`).

- **Tabs** (a control, only when there is more than one): **My requests** (tracked employees), **To review** and **All** (reviewers). The default is *To review* when something is pending, else the first. `?tab=` and `?request=<id>` (opens that request: the Telegram button) are in the URL.
- **My requests:** a **Year** select, then the months of the year, **newest first**, up to the current month and from the month attendance started. Each card: the month, the **balance** (red when negative) and its state:
  - eligible and the window open → **Create request** (*Until 7 Nov*);
  - under an hour → *Under 1 hour — no request needed*;
  - the month hasn't ended → *Opens on 1 Nov*;
  - the window closed with nothing sent → **No request**;
  - a request → its badge (**Pending**, **Approved**, **Approved with changes**, **Rejected**), the split (the approved one when approved) and the reason when rejected; tapping opens it.
- **Create request** (sheet): the month's numbers (absent, late, extra, **missing**); two inputs, **Salary cut** and **Unpaid extra work**, each in **hours + minutes** (minutes over 59 carry into the hours); quick buttons **All salary cut** / **All unpaid work**; the live line *Covered 6 h 45 of 6 h 45 ✅* (green when equal, red otherwise); an optional **note** (500); the warning *You can submit only one request for this month. It can't be changed afterwards.*; **Submit request** is enabled only when the split matches. It starts as everything unpaid extra work.
- **Reviewers:** **To review** = the pending requests, oldest first. **All** adds filters: **Status** (incl. **No request**), **Year**, **Month** and **Employee** (a select, shown with `users.view`); 20 per page (‹ ›). A row: the employee, the month, the missing time, the requested split, the note, the status badge and when it was sent. **No request** rows (an eligible month whose window is over) have no sheet: they open the employee's attendance for that month (with `attendance.view`).
- **Request sheet** (drawer on PC, bottom sheet on phones): the employee, the status, the month's numbers **as they were when it was sent**, the requested split with the sent time, the note, the approved split (*Changed by the reviewer* when it differs), the comment or the rejection reason, who decided and when, a 🔒 hint while the month is locked, and *Open attendance →* for the employee's month (`attendance.view`). A reviewer with a pending request (never their own) gets **Approve**, **Approve with changes** and **Reject**, each with a small form: Approve — an optional comment; Approve with changes — the split editor (starts at the requested split, must cover the missing time) and a comment; Reject — a required reason.
- After a submit or a review the requests, that request, the summaries and the day views refetch. Errors are translated (`ATTENDANCE_REQUEST_WINDOW_CLOSED` with the dates, `…_EXISTS`, `…_SPLIT_MISMATCH`, `…_NOT_PENDING`, `ATTENDANCE_MONTH_LOCKED`, …).

**On My attendance and an employee's page (§7.3, §7.4)**, for a **monthly** period, a slim **status strip** under the KPI cards:

- ✅ *Request approved — salary cut 2 h · unpaid extra work 4 h 45 (approved by … on …)*, with *Changed from …* and the comment when it was approved with changes;
- ⏳ *Request pending review*; ❌ *Request rejected — {reason}*;
- eligible, window open, no request: *Balance −6 h 45 — Create request* (a link to this page on My attendance);
- the window closed with no request: *No request submitted*;
- a **🔒 Month locked** badge at the end of the strip while a pending or approved request locks the month. The Fix / Add actions are then off for that month (a hint replaces *Tap a shift to fix it*). In a whole-year view the API refuses a fix in a locked month (`ATTENDANCE_MONTH_LOCKED`).

**Settings → Workplaces** ends with a **Requests** card, for the **superadmin only**: *Request deadline (day of next month)*, 1–28 (default 7), **Save** (`PUT /attendance/settings/requests`).

**Scheduling** messages (holiday / weekday saves) add *N records were left alone: those months have a pending or approved request* when `skipped_locked` is set.

**The bell and Telegram:** 📝 *{name} sent a request for October 2026: missing 6 h 45 — salary cut 2 h, unpaid extra work 4 h 45* (reviewers), ✅ approved (*with changes* + the comment), ❌ rejected (the reason) and 🔔 the 1st-of-month reminder. A request alert opens `/attendance/requests?request=<id>`; the reminder opens the page.

## 8. Settings

**Path:** `/settings`. **Who can open it:** everyone.

- A hub with one card per Settings page the user may open. Each card has an icon, a title and a one-line description:

  | Card | Shown to |
  |---|---|
  | Users | holders of `users.view` |
  | Audit log | superadmin; general managers given Audit log (`audit.view`) |
  | User limits | superadmin |
  | Business info | superadmin; general managers given Business info (`settings.business_info`) |
  | Workplaces | superadmin; general managers with Workplaces ≥ View only (default) |
  | My profile | everyone |

- The cards come from the same menu definition as the sidebar, so a new Settings page appears here automatically.

### 8.1 User limits (ចំនួនអ្នកប្រើប្រាស់), superadmin only

**Path:** `/settings/user-limits`. How many **active** users each role may have: **General manager** (default 2), **Supervisor** (default 3) and **Staff** (default 10).

- One row per role: *"2 / 3 active"*, a number input (1–999) and **Save**, with an inline *Saved* or error. Supervisor and Staff also have an **Unlimited** checkbox; general managers always have a limit of at least 1.
- **Over the limit** (after lowering it): an amber warning on the row, e.g. *"4 active — above the limit of 3. No new supervisors can be added until someone is deactivated."* Nobody is deactivated automatically.
- *Last changed by … · time* under each changed row, and a note that only active users count.
- Changes are in the audit log as *Changed user limit* (*"Staff: 10 → 12"*), visible to the superadmin only.

### 8.2 Business info (ព័ត៌មានអាជីវកម្ម)

**Path:** `/settings/business-info` (lazy-loaded). **Who can open it:** holders of `settings.business_info`: the superadmin, and a general manager whose **Business info** the superadmin set to Full access on its Access tab (default Off). Menu icon: building.

What every delivery note prints at the top and bottom:

- **Business name** (Khmer, English; both required), **Address** (Khmer, English; line breaks kept), **Phone** (any separators; shown formatted after saving), **Footer note** (Khmer, English; optional, e.g. *"សូមអរគុណ!"* / *"Thank you!"*). **Save** (enabled when something changed); *"Business info saved."*; *Last changed … by …* under the form.
- **Logo:** a preview, **Upload logo** / **Change logo** (PNG or JPEG up to 500 kB; checked before uploading, then by the API; stored at most 400 px wide) and **Remove**. Printed in black and white, so simple dark logos print best.
- **Preview** (header): opens a sample delivery note PDF in a new tab, marked **SAMPLE**: the latest order when the person can see orders, otherwise made-up data. Not counted as a print.
- Changes are in the audit log as *Changed business info* with the changed fields (*"Phone, Logo changed"*).

### 8.3 Workplaces (កន្លែងធ្វើការ)

**Path:** `/settings/attendance/workplaces` (lazy-loaded): where people check in (location, radius, default, delete). **Who can open it:** holders of `attendance.workplace_view`, `attendance.workplace_update` or `attendance.workplace_manage` (the superadmin; general managers with Workplaces ≥ View only, the default). Each workplace has **its own schedule**, managed in Attendance → **Scheduling** (§7.6); staff and supervisors check in at the one they are assigned to (user form, §9).

**List**

- Every active workplace, the default first: name, **Default** badge, *No location* when its position isn't set, address, the number of employees and both shifts' times (*Morning shift 07:00–12:00 · Afternoon shift 13:00–15:00*). **Show archived** adds archived ones (badge) (`?archived=1`).
- **New workplace** (`attendance.workplace_manage`): name, address, the map picker and radius (as below). Its schedule is a copy of the default workplace's current one; after **Create** its page opens.

**Workplace page** (`/settings/attendance/workplaces/:id`): the header shows the name, *Default* / *Archived* and *Last changed by … · time*.

By permission: Workplaces **View only** sees everything read-only; **Record** (`attendance.workplace_update`) also edits the Location (name, address, map pin, radius) of existing workplaces but sees no **New workplace**, **Make default**, **Delete / Archive** or **Restore**; **Full access** (`attendance.workplace_manage` too) sees all of them.

- **Location** (edit with `attendance.workplace_update`, read-only otherwise; **Make default**, **Delete / Archive** and **Restore** with `attendance.workplace_manage`):
  - **Name**, **Address**; a **map picker** (Leaflet + OpenStreetMap): tap to place the pin, the radius circle drawn on the map; latitude and longitude fields (6 decimals; both or neither); **Radius** slider (10 m steps up to 1000 m) with a number field (10–5000 m). Without a position, a warning: nobody there can check in until it's set.
  - **Make default** (confirmation: new staff and supervisors get it unless another workplace is chosen; nobody is moved). Disabled until the location is set.
  - **Delete**, or **Archive** when it has attendance history (confirmation explains which). Disabled while employees are assigned, with *"Can't delete: 2 employees are assigned here."* and a **See them** link to the users list filtered by this workplace; the default shows *"The default workplace can't be deleted. Make another one the default first."*
  - Archived: a notice (nobody checks in there, it can't be edited) and **Restore**.
- **Schedule**, read-only: *Current schedule, since …*, the tracked weekdays, both shifts with their windows (check-in, absent from, check-out, forgot from), reminders and the extra-time flags. **Edit in Scheduling** (`attendance.scheduling`; *View in Scheduling* with `attendance.view` only) opens this workplace's scheduling.
- **Employees**: the active staff and supervisors assigned (name, role, position), linking to their user page with `users.view`.

## 9. Users

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
  - **workplace** (shown when there is more than one): the staff and supervisors assigned to it (`?workplace=` preselects it, e.g. from a workplace's *See them* link);
- **Not tracked badge:** a small grey *Not tracked* / មិនតាមដាន badge next to the status badges of a supervisor whose attendance is switched off (list and user page).
  - **status**: active (default), deactivated, or all.
- Each row or card shows avatar initials, name, `@telegram`, role/position badge, phone and status badges:
  - *Active* / *Deactivated*;
  - *Locked*;
  - *Password change pending*.
- **Telegram not linked yet:** a grey badge next to `@telegram` (desktop) or with the badges (mobile) for an active user whose Telegram isn't linked, so managers see whose alerts and reminders can't reach Telegram yet. On the user page the Telegram line shows *Telegram linked* / *Telegram not linked yet*, and when not linked: *"Ask them to open the bot and press Start."*
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
- **Workplace** (staff and supervisors): a select of the active workplaces where they check in (Attendance, §7), the default preselected for new users (`GET /attendance/workplace-options`, readable with `users.view`). Editing moves them to another one (from the next window); someone whose workplace was archived keeps showing it until moved. The user's page shows it too.
- **Attendance start date / ថ្ងៃចាប់ផ្តើមចុះវត្តមាន** (staff and supervisors): a date picker, minimum today, default today, hint *"Attendance is tracked from this date"*. When editing it is editable only while the date is still in the future; once it has arrived it shows as read-only text (*Attendance started on this date; it can't be changed.*). A date in the past is refused (*"The attendance start date can't be in the past."*) and a locked one by the API (`ATTENDANCE_START_LOCKED`).
- **Track attendance / តាមដានវត្តមាន** (supervisors, **edit form only**, general manager and superadmin): a checkbox, on by default, hint *"When off, this supervisor doesn't check in and isn't counted."* Switching it off asks for confirmation (*"Takes effect now; today's records are kept."*) and takes effect when saved; switching it on again resumes tracking from today. Staff are always tracked, so they have no toggle.
- **Live login preview:** "Signs in as: sok_dara" shows how the username will be normalized.
- **Initial-password note:** the initial password is the Telegram username, and it must be changed at first sign-in.
- **After saving,** it opens the new user's page with a confirmation showing the initial password.

**Edit a user** (`users.update`; supervisors only at Staff management *Full access*)

- Same fields; the role isn't edited here (see **Change role** on the user's page, §10). Staff can be given a new position at any time; it has no effect on their access.
- If the user is linked to Telegram and you change their username, a warning says the link will be removed.

## 10. User detail

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
    - Moving a general manager into staff or supervisor also asks for the **attendance start date** (date picker, minimum today, default today). Staff ↔ supervisor keeps the existing date. Supervisor → staff switches attendance tracking back on.

- **Details tab:**
  - full name, Telegram username and whether it's **linked** to a Telegram account;
  - role, position (shown exactly as entered, never translated), phone, language;
  - for staff and supervisors the **attendance start date**, and for supervisors **Attendance: Tracked / Not tracked since {date}**;
  - created, updated and deactivated dates;
  - locked-until time, if the account is locked.
- **Tabs**, by viewer (§11):

  | Viewer | Details | Access | Permissions (advanced) |
  |---|---|---|---|
  | General manager (supervisor / staff) | ✅ | ✅ | — |
  | Supervisor (staff) | ✅ | ✅ with Staff access (default) | — |
  | Superadmin (general manager, supervisor, staff) | ✅ | ✅ | ✅ |

  A supervisor opening a staff member without *Edit* (the default) sees a read-only page: Details, plus the Access tab when it has Staff access. Nobody sees an Access tab on their own profile, and staff never see one.

  When the superadmin opens the **general manager**, the Access tab shows the GM's levels for Suppliers, Customers, Production, Production plan and Staff management (only the superadmin can change them); the GM-only powers are on Permissions (advanced).

  A `?tab=` the viewer can't open falls back to Details.
- Success and error messages are shown inline and are translated.

## 11. Access tab and Permissions (advanced)

### Access tab (ការចូលប្រើ)

How general managers decide what supervisors and staff can use (and how the superadmin decides what each general manager can use), and how **supervisors** decide what their **staff** can use. Shown when the viewer may manage access (*can manage features*) and at least one feature applies to the user. A general manager can set **any level of any feature** available to that user's role; nothing here depends on the general manager's own permissions.

- **Supervisors** (with **Staff access**, on by default) see the Access tab of **staff** only, with the same layout: Suppliers, Customers and Production. They can give a level **up to their own** (what a GM or the superadmin gave them): higher segments are disabled, with the tooltip *"Higher than your own access"* (*ខ្ពស់ជាងសិទ្ធិរបស់អ្នក*). *Off* and lower levels are always available, also for a level a GM set higher. If the server still refuses (the supervisor's access was lowered meanwhile), the message reads *"You can't give more access than you have."* When a GM lowers the supervisor later, levels the supervisor already gave stay as they are.
- **Grouped by menu:** **Workstation** (Suppliers, Customers, Production, Production plan: GM and supervisors only), then **Attendance** (Attendance and Attendance corrections: GM and supervisors; Workplaces: general managers only, so only on the superadmin's view of a GM; **Attendance scheduling**: see below; nothing for staff), then **Settings** (Staff management: supervisors, and general managers when the superadmin views them; **Staff access**: supervisors only).
- Each row: the feature's name and a one-line description (from the server, in the current language), and a segmented control with the levels the server lists for that feature: **Off · View only · Full access** (*បិទ · មើលតែប៉ុណ្ណោះ · ពេញលេញ*); for Production, Staff management and Workplaces **Off · View only · Record · Full access** (*បិទ · មើលតែប៉ុណ្ណោះ · កត់ត្រា · ពេញលេញ*); for Staff access **Off · Full access**, described as *"Can set what staff can use, up to their own access."*
- A legend at the top: *View only* = can see the list; *Record* = can start batches and fill in steps, but can't reopen finished steps (shown when Production is listed); *Full access* = can add, edit and deactivate, and in Production also reopen finished steps. When Production plan is listed: *"Production plan: View only = see plans and receive production alerts; Full access = also set and confirm plans."* When Staff management is listed: *"Staff management: View only = see staff; Record = also add staff; Full access = also edit their info."* (supervisors never deactivate people). When Staff access is listed: *"Staff access: Full access = can set what staff can use, up to their own access."* When Workplaces is listed (the superadmin's view of a GM): *"Workplaces: Record = edit existing workplaces (location, radius), but not create or delete."*
- **Each click saves** immediately, with a spinner on that row. On error the previous level comes back and a translated message is shown.
- From *Off*, *View only* has a dashed outline as the suggested next step; it still takes a click.
- **Custom:** if a user's permissions match no level (only possible through the superadmin's detailed permissions), a neutral *Custom* badge is shown and no level is selected. Picking a level replaces it.
- **Attendance requests** (Off · Full access, under Attendance; GM Full, supervisor Off) is listed for general managers and supervisors like the other Attendance features (the Access tab reads the feature list from the server, so it appears by itself).
- **Inventory history** (Off · View only, under Workstation) and **Attendance scheduling** (Off · Full access, under Attendance) appear only where the viewer may give them: the superadmin on general managers and supervisors, and a general manager on supervisors **only while that GM has it**. A GM without it never sees the row, with no hint. Both default to Off.
- **Audit log** (Off · View only, under Settings) is listed only on a general manager, so only the superadmin sets it; default Off. *View only* opens Settings → Audit log for that GM (with its usual filtering); *Off* removes it again.
- Rows are disabled only when the user is deactivated; single segments only when above a supervisor's own access. No explanation mentions other roles.
- Defaults: supervisors start with Suppliers, Customers and Production at **Full access**, **Production plan Off**, **Staff management View only** and **Staff access Full access**; staff with everything **Off**; general managers at **Full access**. Supervisors who had Staff management at Full access before this default changed were moved to View only once (audit log: *"New default for supervisors"*, by System).
- **General manager as the target** (superadmin only): a hint under the legend says *"Deactivating users, resetting passwords, managing access and cancelling batches are set in Permissions (advanced)."* Lowering Staff management takes creating / editing users (at *Off*, the Users list) away from the GM.
- Changes take effect on the user's next menu refresh (within a minute, or at once on their next "no permission" answer). If you change your own access, your menus refresh immediately.
- **Every row has the same columns, in the same order:** Off · View only · Record · Full access. A feature without a level (Record exists only for Production and Staff management; Staff access has only Off and Full access) shows a muted "—" in that column (tooltip: *Not available for this feature*), so each level sits in the same place for every feature. On large screens the columns have one fixed width and line up exactly; on tablets, phones and in the Mini App the control sits under the name, full width, with large touch targets, as a 2 × 2 grid on phones. If no feature on the tab has Record, the column isn't shown.

### Permissions (advanced), superadmin only

Only for the superadmin. Shows the detailed permissions under the feature levels: grouped by module, each with its localized name, description and code, a checkbox, and a lock reason from the server when it can't be changed (e.g. the user is deactivated). Clicking a checkbox grants or revokes that one permission immediately. General-manager-only permissions (deactivate users, reset passwords, manage access, cancel production batches) are managed here. Revoking *manage access* from the GM removes the GM's Access tab.

Supervisors never see detailed permissions; they see feature levels only on the Access tab of their staff (with Staff access). Staff never see any permission or access information.

## 12. Audit log

**Path:** `/settings/audit-logs`. **Who can open it:** holders of `audit.view`: the superadmin always, a general manager only when the superadmin sets its **Audit log** feature to *View only* (Access tab; default Off). Without it the menu item and the Settings card are hidden and the address shows *No access*. General managers don't see entries made by the superadmin (nor detailed permission changes).

- A chronological list of security events:
  - sign-ins and failed sign-ins;
  - lockouts;
  - password changes and resets;
  - user creation, edits, role changes (e.g. *"Staff → Supervisor"*), deactivation and reactivation;
  - access changes (*Changed access*), shown as e.g. *"Suppliers: View only → Full access"*;
  - detailed permission grants and revokes, including automatic ones on deploy (*Granted automatically (role default)*, or *Granted automatically (access levels changed, the level stays the same)* when a level is split, e.g. Workplaces' Record in migration 0024): **superadmin only** (general managers see access changes instead);
  - profile updates;
  - suppliers and customers added, edited, deactivated and reactivated;
  - production: batch started, step finished and step reopened (*"Step 1 · Intake"*, plus *"Also back to draft: step 2, 3"* when later steps were reopened with it), batch cancelled (with the reason). Draft saves aren't logged;
  - packaging plans: *Edited packaging plan* (field changes in the details) and *Confirmed packaging plan* (*"148 × 4-piece · 4 × 2-piece"*), linked to the batch;
  - preparations: started, finished (the sachets made or the materials moved), reopened, cancelled (with the reason), linked to the preparation;
  - orders: created, edited, cancelled (with the reason), out for delivery, delivered (*Everything accepted* / *Items returned* and the reason), return reviewed (*Partly* / *Fully returned*), delivery note printed (*Original* / *Copy #n*, downloaded or sent to Telegram), linked to the order;
  - business info changed (the changed fields; the superadmin's changes are hidden from general managers);
  - the system account linking or unlinking its Telegram (superadmin only).
- **Filters:** record type (All · Suppliers · Customers · Production batches · Orders · Materials · Preparations) and action type.
- Each entry shows:
  - the time, in the current language's format;
  - the action, as a translated badge, red for failures and locks;
  - **By** (actor) and **User** (target), linking to the user. Actions by the system show **System** (ប្រព័ន្ធ), without a link;
  - for supplier / customer entries, the **record**: its type and current name, linking to the Suppliers / Customers page with that name already searched (including deactivated records); for production entries, the batch code, linking to the batch;
  - details: the permission code, or an expandable JSON view.
- **Revocations are highlighted.** When a revoked permission had been passed on to others by that user, an amber warning lists who still holds it, so managers can follow up (revoking does not cascade).
- Pagination, with 50 per page.

## 13. My profile

**Path:** `/settings/profile` (also from the avatar menu). Available to every user, including staff.

**Personal information**

- Edit your full name, phone and language.
- Saving the language switches the whole UI.

**Account**

- Shows your role and Telegram username, and whether Telegram is linked.
- No permission or access information is shown, for any role.

**Telegram** (system account only)

- Status *Telegram linked* / *Telegram not linked yet*. **Link Telegram** creates a one-time link and shows **Open the bot** (*"Opens the bot; valid for 10 minutes. Tap Start there."*); after tapping Start in Telegram, the card shows *Linked* when you come back to the window. **Unlink** (with confirmation) stops the alerts on Telegram. Other accounts link Telegram by signing in to the Mini App or by pressing Start in the bot (Home asks them to, §5).

**Change password**

- Current password, new password and confirmation, with the same rules as §3.

**Reset my password** (general manager)

- Returns your password to your Telegram username and signs you out on all devices. You must change it at next sign-in. (The superadmin's reset returns it to its initial password instead.)
- After confirming, you're taken to the login page with a message telling you which password to use.

## 14. Language (Khmer / English)

- **Khmer is the default.** English is fully supported: every label, message, role, audit action and error, including the supplier / customer / production pages, their figures and autosave states. Positions are free text and are shown as entered.
- **Switching** from the header takes effect instantly.
  - **Signed in:** the choice is saved to your profile and follows you to other devices.
  - **Signed out, or password change pending:** it is remembered on this device.
- **Your saved language is applied** automatically after sign-in.
- **Permission and module names** come from the server in both languages.
- **Errors are translated too,** including messages coming from the server. Example: *"ឈ្មោះអ្នកប្រើ ឬពាក្យសម្ងាត់មិនត្រឹមត្រូវ។"* / *"Incorrect username or password."*
- **Typography:** the Kantumruy Pro font with Khmer-friendly line height.

## 15. Error and status screens

| Situation | What the user sees |
|---|---|
| Page not allowed | "No access" with a link home. |
| Unknown page | "Page not found". |
| Server unreachable while restoring a session | A network error message and **Try again**. The session is kept. |
| Session expired | Refreshed silently. If that fails, the user is sent back to login. |
| Account deactivated while signed in | Signed out on the next request. |
| Password reset by a manager while signed in | Redirected to the forced password change. |

## 16. Screen access matrix

| Screen | Superadmin | General manager | Supervisor | Staff |
|---|---|---|---|---|
| Home, Workstation, Settings hub | ✅ | ✅ | ✅ | ✅ |
| Settings → My profile | ✅ | ✅ | ✅ | ✅ |
| Settings → Users (list / detail) | ✅ all below | ✅ supervisors, staff | Staff management ≥ View only (default View only): staff | ❌ |
| Add staff | ✅ | ✅ | Staff management ≥ Record (only if allowed; default View only) | ❌ |
| Edit staff info | ✅ | ✅ | Staff management = Full (only if allowed) | ❌ |
| Change role (promote / demote) | ✅ GM ↔ supervisor ↔ staff | ✅ supervisor ↔ staff | ❌ | ❌ |
| Settings → User limits (role limits) | ✅ | ❌ | ❌ | ❌ |
| Settings → Business info (edit, logo, preview) | ✅ | Business info = Full (default Off; set by the superadmin) | ❌ never | ❌ never |
| Role capacity in the users list and forms | ✅ all three roles | ✅ supervisors, staff | ✅ staff | ❌ |
| Deactivate / reactivate users | ✅ | ✅ | ❌ never | ❌ |
| Reset others' password | ✅ | ✅ | ❌ never | ❌ |
| Reset own password | ✅ | ✅ | ❌ | ❌ |
| User detail → Access tab | ✅ | ✅ (supervisors, staff) | Staff access = Full (default ✅): staff only, up to its own levels | ❌ |
| Set staff access (Suppliers, Customers, Production of staff) | ✅ | ✅ | ✅ default (Staff access), never above its own | ❌ |
| User detail → Permissions (advanced) | ✅ | ❌ | ❌ | ❌ |
| Settings → Audit log | ✅ everything | only if the superadmin allows it (Audit log, default Off); then without detailed permission entries | ❌ | ❌ |
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
| Workstation → Inventory (stock, wasted, materials, item sheet with the per-batch breakdown) | ✅ | Inventory ≥ View only (default Record) | Inventory ≥ View only (default Record) | Inventory ≥ View only (default Off) |
| Inventory → History tab, item's recent changes; batch page → Stock changes | ✅ | Inventory history = View only (default Off; given by the superadmin) | Inventory history = View only (default Off; given by the superadmin or a GM who has it) | ❌ never |
| Set stock by hand | ❌ never (production items) | ❌ never | ❌ never | ❌ never |
| Add / remove material stock (Raw) | ✅ | Inventory = Record (default) | Inventory = Record (default) | Inventory = Record (default Off) |
| Add, edit, archive, restore materials; Show archived | ✅ | Inventory materials = Full (default) | Inventory materials = Full (default Off) | ❌ never |
| Workstation → Orders (list, order page) | ✅ | Orders ≥ View only (default Record) | Orders ≥ View only (default Record) | Orders ≥ View only (default Off) |
| Create orders, Start delivery, Mark delivered (incl. returns) | ✅ | Orders = Record (default) | Orders = Record (default) | Orders = Record |
| Edit / cancel Created orders | ✅ | Order management = Full (default) | Order management = Full (default Off) | ❌ never |
| Review returns; order alerts (bell, Telegram) | ✅ | Order returns = Full (default) | Order returns = Full (default Off) | ❌ never |
| Workstation → Preparation (list, preparation page, figures) | ✅ | Preparation ≥ View only (default Record) | Preparation ≥ View only (default Record) | Preparation ≥ View only (default Off) |
| Create, fill in and finish preparations | ✅ | Preparation = Record (default) | Preparation = Record (default) | Preparation = Record |
| Reopen / cancel preparations; preparation alerts (bell, Telegram) | ✅ | Preparation management = Full (default) | Preparation management = Full (default Off) | ❌ never |
| Inventory → Prepared sub-tab (sachets, prepared materials; no manual changes) | ✅ | Inventory ≥ View only | Inventory ≥ View only | Inventory ≥ View only |
| Delivery note: Export PDF / Excel (needs *Export delivery note*; GM yes by default) | ✅ | ✅ | Granted only | Granted only |
| Delivery note: Send to my Telegram (any status) | ✅ | Orders ≥ View only | Orders ≥ View only | Orders ≥ View only |
| Attendance → check screen, My attendance, Home card (check in / out) | ❌ (not tracked) | ❌ (not tracked) | ✅ always | ✅ always |
| Turn supervisor attendance on / off (User form → Track attendance) | ✅ | ✅ | ❌ never | ❌ never |
| Attendance → Today (each day's attendance in scope) | ✅ staff and supervisors | Attendance = View only (default) | Attendance = View only (default Off): staff | ❌ never |
| Fix / add attendance records | ✅ | Attendance corrections = Full (default) | Attendance corrections = Full (default Off): staff | ❌ never |
| Settings → Workplaces (view: list, location, schedule read-only, employees) | ✅ | Workplaces ≥ View only (default; set by the superadmin) | ❌ never | ❌ never |
| Edit existing workplaces (name, address, map pin, radius) | ✅ | Workplaces ≥ Record (default View only; set by the superadmin) | ❌ never | ❌ never |
| Create, delete / archive, restore workplaces; make default | ✅ | Workplaces = Full (default View only; set by the superadmin) | ❌ never | ❌ never |
| Attendance → Scheduling, read-only (calendar, holidays, weekdays, schedule) | ✅ | Attendance = View only (default) or Attendance scheduling | Attendance = View only or Attendance scheduling (default Off) | ❌ never |
| Manage tracked weekdays, holidays, shift times and rules (one, several or all workplaces) | ✅ | Attendance scheduling = Full (default Off; set by the superadmin) | Attendance scheduling = Full (default Off; set by a GM who has it) | ❌ never |
| Attendance → Requests: send my month's request, read it | ❌ (not tracked) | ❌ (not tracked) | ✅ always | ✅ always |
| Attendance → Requests: review (approve, approve with changes, reject) | ✅ staff and supervisors | Attendance requests = Full (default) | Attendance requests = Full (default Off): staff | ❌ never |
| Settings → Workplaces → Request deadline | ✅ | ❌ never | ❌ never | ❌ never |
| User form: choose the workplace of staff / supervisors | ✅ | with Staff management edit | with Staff management Record / Full: staff | ❌ never |
| User form / Change role: attendance start date of staff / supervisors (editable until it arrives) | ✅ | with Staff management edit | with Staff management Record / Full: staff | ❌ never |
| Header bell | ✅ | ✅ | ✅ (empty without plan, order returns or preparation management access) | ✅ (always empty) |
| My profile → Telegram card | ✅ | ❌ | ❌ | ❌ |

"Suppliers = Full" etc. refers to the levels a general manager (for staff also their supervisor) sets on the Access tab (§11). "(default)" is the level a new account starts with.

This matrix depends **only on role and access levels**. A staff member's position (e.g. `Grill cook` or `អ្នកដឹកជញ្ជូន`) never changes it: two staff with the same levels see exactly the same menu and screens.
