# API Architecture

How the Mean Chey Grilled Chicken API is put together, and why. For what it *does*, see [FEATURES.md](FEATURES.md).

- [1. System overview](#1-system-overview)
- [2. Tech stack](#2-tech-stack)
- [3. Code layout and layering](#3-code-layout-and-layering)
- [4. Request lifecycle](#4-request-lifecycle)
- [5. Data model](#5-data-model)
- [6. Authorization model](#6-authorization-model)
- [7. Authentication internals](#7-authentication-internals)
- [8. Startup and bootstrap](#8-startup-and-bootstrap)
- [9. Telegram bot](#9-telegram-bot)
- [10. Error handling](#10-error-handling)
- [11. Configuration](#11-configuration)
- [12. Testing strategy](#12-testing-strategy)
- [13. Deployment](#13-deployment)
- [14. Extending the system](#14-extending-the-system)
- [15. Design decisions](#15-design-decisions)

---

## 1. System overview

```mermaid
flowchart LR
    subgraph Clients
        PC[PC browser<br/>dashboard]
        TG[Telegram app<br/>Mini App WebView]
    end
    subgraph UI[meanchey-grilled-chicken-ui]
        SPA[React SPA<br/>Vite dev server / static host]
    end
    subgraph API[meanchey-grilled-chicken-api]
        FAST[FastAPI app · uvicorn<br/>/api/v1 + /api/telegram/webhook<br/>aiogram Bot + Dispatcher]
    end
    DB[(PostgreSQL 16)]
    TGAPI[Telegram Bot API]

    PC --> SPA
    TG --> SPA
    SPA -- "/api/v1 (JSON, Bearer JWT)" --> FAST
    TGAPI -- "POST /api/telegram/webhook<br/>(secret token header)" --> FAST
    FAST -- "sendMessage, setWebhook…" --> TGAPI
    FAST --> DB
    TG <--> TGAPI
```

- In the default **webhook mode** there is **one process**: the FastAPI app serves the UI's JSON API and receives Telegram updates on `/api/telegram/webhook`. There is no separate bot process.
- The **UI** calls the API only through `/api/v1`. In development the Vite dev server proxies all of `/api` to the API, so one HTTPS tunnel (ngrok / cloudflared) serves the Mini App, `/api/v1` *and* the Telegram webhook.
- **Polling mode** (`BOT_MODE=polling`, local dev without a tunnel) adds back a separate `python -m app.bot` process from the same image. See §9.

## 2. Tech stack

| Concern | Choice |
|---|---|
| Language / runtime | Python 3.12 |
| Web framework | FastAPI, with Pydantic v2 schemas |
| Database | PostgreSQL 16 |
| ORM / driver | SQLAlchemy 2.x async + asyncpg |
| Migrations | Alembic (async `env.py`) |
| Password hashing | argon2-cffi (argon2id), with transparent rehash on login |
| Tokens | PyJWT (HS256) for access tokens; opaque random refresh tokens stored hashed |
| Bot | aiogram 3 |
| Documents (PDF) | Jinja2 templates → WeasyPrint (Pango / HarfBuzz) PDFs; Kantumruy Pro font bundled; segno (QR codes); Pillow (logo resize) |
| Config | pydantic-settings, reading `.env` |
| Tooling | uv (dependencies and lock), ruff (lint and format), pytest + pytest-asyncio + httpx, pypdf (reading PDFs in tests) |

## 3. Code layout and layering

```
app/
├── main.py              # create_app(): middleware, error handlers, routers, lifespan
├── config.py            # Settings (pydantic-settings), cached get_settings()
├── db.py                # async engine + SessionLocal + get_session dependency
├── bootstrap.py         # registry sync + superadmin seed (python -m app.bootstrap)
├── deps.py              # auth dependencies: CurrentUser, PendingUser, require_permission, require_role
├── core/
│   ├── errors.py        # ErrorCode enum, AppError, exception handlers
│   ├── security.py      # argon2, JWT encode/decode, refresh token generation, hash_token (SHA-256)
│   ├── telegram_auth.py # initData HMAC validation
│   ├── usernames.py     # Telegram username normalization/validation
│   └── phones.py        # phone normalization (storage) + formatting (phone_display)
├── models/              # SQLAlchemy ORM (User, Permission, UserPermission, RefreshToken, AuditLog, BotPref, AppSetting,
│                        #   Supplier + Customer via PartnerMixin, production batches + steps + plan,
│                        #   Notification, TelegramLinkToken, InventoryBalance, InventoryMovement,
│                        #   Order, OrderBox, OrderBoxItem, OrderReturnItem, OrderCounter, BusinessSettings)
├── schemas/             # Pydantic request/response models; common.UserRef = the only user-reference shape
├── production/
│   └── catalog.py       # by-products and raw material kinds (code catalogs, no migration to extend)
├── inventory/
│   └── catalog.py       # inventory items (stock / wasted), by-product items generated from production,
│                        #   ORDERABLE (packs + packed by-products), wasted_for(code)
├── documents/           # delivery notes (later invoices): order → HTML → PDF
│   ├── delivery_note.py # build_context (what the note shows), labels km/en, DocumentKind + kind_for
│   │                    #   (delivery note now, invoice once orders have prices), sample_order
│   ├── render.py        # Jinja2 + WeasyPrint (lazy import), two-pass height, thread + timeout
│   ├── templates/       # delivery_note.html.j2, receipt.css (80 mm, black and white)
│   └── fonts/           # Kantumruy Pro Regular / Bold (static instances) + OFL.txt
├── permissions/
│   ├── registry.py      # PERMISSIONS, MODULES, FEATURES, DEFAULT_PERMISSIONS  ← feature authors edit this
│   ├── features.py      # feature access levels: current level, matrix, set_level (diff + feature.set audit)
│   ├── sync.py          # registry → DB sync + default backfill for new permissions
│   ├── hierarchy.py     # role scope: MANAGEABLE_ROLES, can_manage, ensure_can_manage
│   └── service.py       # effective permissions, grant/revoke rules, defaults, permission matrix
├── services/
│   ├── auth_service.py  # login (password/Telegram), tokens, change/reset password, /me
│   ├── user_service.py  # user CRUD, activation, resets, profile
│   ├── partner_service.py # generic supplier/customer CRUD, search, stats (PartnerKind)
│   ├── production_service.py # batches: drafts + versions, finish / reopen / cancel, codes, stats, plan gate
│   ├── plan_service.py  # packaging plans: list, detail, save, confirm (batch version, pieces rule)
│   ├── notification_service.py # alert recipients (per permission), rows in the action's transaction, the bell
│   ├── order_service.py # orders: boxes, status flow, returns, codes, list / stats / options, summary
│   ├── document_service.py # delivery notes: count (print_count) + render + audit, preview
│   ├── business_service.py # business info row (get-or-create), text fields, logo (validate, resize)
│   ├── telegram_link_service.py # superadmin one-time Telegram link (create, consume, unlink)
│   ├── role_limit_service.py # role limits: ensure_slot (row lock + count), settings, capacity
│   ├── inventory_service.py # ledger: apply_movements (locks, no-negative), production hooks, per-batch
│   │                        #   breakdown (item_detail), orders (take_for_order FIFO, return_from_order),
│   │                        #   production guard, adjustments (manual items only; none today)
│   ├── audit_service.py # record() + listing (viewer-aware filters)
│   └── redaction.py     # hides the superadmin from other viewers: viewer context, hides(), middleware
├── api/                 # thin routers: auth, me, users, permissions (superadmin), features, audit,
│                        #   partners (build_router(kind) → /suppliers, /customers), production,
│                        #   production_plans, notifications, settings (role limits, business info), inventory,
│                        #   orders (incl. document.pdf, document/send-telegram)
└── bot/
    ├── setup.py         # create_bot(), create_dispatcher(): the one place handlers are registered
    ├── handlers.py      # /start (incl. /start link_<token>), /lang (create_router())
    ├── notify.py        # send stored alerts after commit (deliver, resend_failed), bot username,
    │                    #   api_bot (which bot the API sends with), send_document (delivery notes)
    ├── i18n.py          # bot texts (km/en)
    ├── webhook.py       # POST /api/telegram/webhook (secret check → dp.feed_update)
    ├── runtime.py       # TelegramRuntime (Bot + Dispatcher on app.state), create_runtime()
    ├── registration.py  # ensure_webhook / set / delete / info, fingerprint in app_settings
    └── __main__.py      # CLI: polling mode, `webhook set|delete|info`, `notifications resend-failed`
```

**Layering rules**

```mermaid
flowchart TD
    R[api/* routers] --> D[deps.py guards]
    R --> S[services/*]
    R --> P[permissions/service]
    D --> P
    S --> P
    S --> A[services/audit_service]
    P --> A
    S --> M[models]
    P --> M
    S --> C[core/*]
    D --> C
```

- **Routers** are thin. They parse input with Pydantic, declare guards through dependencies, call one service function, and serialize the result.
- **Services** hold the business rules and own the transaction: they call `session.commit()`. Audit entries are added through `record()` inside the same transaction, so an action and its audit row commit or roll back together.
- **Guards** in `deps.py` and `permissions/hierarchy.py` are pure checks that raise `AppError`.
- **`core/`** has no dependency on models or services, apart from `errors`.
- **Redaction** sits at the serialization edge: `deps.get_current_user_allow_pending` records the viewer in a context variable (reset per request by `ViewerContextMiddleware`), and `UserRef`'s serializer hides the superadmin for any other viewer. Services never special-case it, except lookups (`get_user_or_404(..., viewer)`) and the audit filters.

## 4. Request lifecycle

```mermaid
sequenceDiagram
    participant C as Client
    participant F as FastAPI
    participant Dep as deps.py
    participant Svc as Service
    participant DB as PostgreSQL

    C->>F: PATCH /api/v1/users/{id} (Bearer JWT)
    F->>Dep: get_session() → AsyncSession (one per request)
    F->>Dep: get_current_user_allow_pending()
    Dep->>Dep: decode JWT (TOKEN_EXPIRED / INVALID_TOKEN)
    Dep->>DB: SELECT user by id
    Dep-->>F: 401 ACCOUNT_DISABLED if inactive
    F->>Dep: get_current_user()
    Dep-->>F: 403 PASSWORD_CHANGE_REQUIRED if pending
    F->>Dep: require_permission("users.update")
    Dep->>DB: effective permissions
    Dep-->>F: 403 MISSING_PERMISSION if missing
    F->>Svc: update_user(session, actor, target, body)
    Svc->>Svc: ensure_can_manage(actor, target) → FORBIDDEN_SCOPE
    Svc->>DB: UPDATE users …; INSERT audit_logs
    Svc->>DB: COMMIT
    F-->>C: 200 UserOut
```

- FastAPI caches a dependency per request, so the guard dependencies and the handler share the **same session**.
- Business-rule failures raise `AppError`, which becomes a JSON error (§10).

## 5. Data model

```mermaid
erDiagram
    users ||--o{ user_permissions : "holds"
    permissions ||--o{ user_permissions : "granted as"
    users ||--o{ user_permissions : "granted_by"
    users ||--o{ refresh_tokens : "has"
    users ||--o{ audit_logs : "actor"
    users ||--o{ audit_logs : "target"
    users ||--o{ users : "created_by"
    users ||--o{ suppliers : "created_by / updated_by"
    users ||--o{ customers : "created_by / updated_by"
    suppliers ||..o{ audit_logs : "entity (no FK)"
    customers ||..o{ audit_logs : "entity (no FK)"
    production_batches ||--|| production_raw_materials : "step 1"
    production_batches ||--o| production_outputs : "step 2"
    production_batches ||--o| production_packaging : "step 3"
    production_batches ||--o{ production_byproducts : "per catalog item"
    suppliers ||--o{ production_raw_materials : "supplier_id (RESTRICT)"
    users ||--o{ production_batches : "created_by / updated_by / cancelled_by"
    production_batches ||..o{ audit_logs : "entity (no FK)"
    production_batches ||--o| production_plans : "packaging plan"
    users ||--o{ production_plans : "confirmed_by / updated_by"
    users ||--o{ notifications : "recipient (CASCADE)"
    production_batches ||..o{ notifications : "entity (no FK)"
    users ||--o{ telegram_link_tokens : "one-time link"
    users ||--o{ role_limits : "updated_by"
    production_batches ||--o{ inventory_movements : "batch_id (SET NULL)"
    inventory_movements ||--o| inventory_movements : "reversal_of (unique)"
    users ||--o{ inventory_movements : "created_by"
    inventory_balances ||..o{ inventory_movements : "item_code (no FK)"
    customers ||--o{ orders : "customer_id (RESTRICT)"
    users ||--o{ orders : "driver_id / created_by / … (SET NULL)"
    orders ||--o{ order_boxes : "boxes (CASCADE)"
    order_boxes ||--o{ order_box_items : "lines (CASCADE)"
    orders ||--o{ order_return_items : "returns (CASCADE)"
    orders ||--o{ inventory_movements : "order_id (SET NULL)"
    orders ||..o{ audit_logs : "entity (no FK)"
    orders ||..o{ notifications : "entity (no FK)"
    users ||--o{ business_settings : "updated_by (one row)"

    users {
        uuid id PK
        user_role role "PG enum"
        varchar50 position "staff only, free-text label"
        varchar full_name
        varchar phone
        varchar telegram_username "normalized"
        bigint telegram_user_id "bound on first Mini App login"
        varchar password_hash "argon2id"
        bool must_change_password
        varchar language "km | en"
        bool is_active
        uuid created_by FK
        timestamptz created_at
        timestamptz updated_at
        timestamptz deleted_at
        int failed_login_count
        timestamptz locked_until
    }
    permissions {
        varchar code PK
        varchar module
        varchar name_en
        varchar name_km
        text description_en
        text description_km
        varchar_array assignable_to
        jsonb grantable_by "target role → grantor roles"
        bool is_active
    }
    user_permissions {
        uuid user_id PK,FK
        varchar permission_code PK,FK
        uuid granted_by FK
        timestamptz granted_at
    }
    refresh_tokens {
        uuid id PK
        uuid user_id FK
        varchar token_hash UK "sha256"
        timestamptz expires_at
        timestamptz revoked_at
        uuid replaced_by
    }
    audit_logs {
        bigint id PK
        uuid actor_id FK
        varchar action
        uuid target_user_id FK
        varchar entity_type "supplier | customer | production_batch"
        uuid entity_id "no FK"
        jsonb details
        timestamptz created_at
    }
    suppliers {
        uuid id PK
        varchar150 name
        varchar255 location
        varchar20 phone "normalized, unique among active"
        bool is_active
        timestamptz deleted_at
        uuid created_by FK
        uuid updated_by FK
        timestamptz created_at
        timestamptz updated_at
    }
    customers {
        uuid id PK
        varchar150 name
        varchar255 location
        varchar20 phone "normalized, unique among active"
        bool is_active
        timestamptz deleted_at
        uuid created_by FK
        uuid updated_by FK
        timestamptz created_at
        timestamptz updated_at
    }
    bot_prefs {
        bigint telegram_user_id PK
        varchar language
    }
    production_batches {
        uuid id PK
        varchar32 code UK "PR-YYYYMMDD-NNN (creation day)"
        varchar status "in_progress | completed | cancelled"
        smallint current_step "1-3"
        varchar500 cancel_reason
        int version "optimistic concurrency"
        bool inventory_tracked "false for batches before migration 0010"
        uuid created_by FK
        uuid updated_by FK
        uuid cancelled_by FK
        timestamptz created_at
        timestamptz updated_at
        timestamptz cancelled_at
        timestamptz completed_at
    }
    production_raw_materials {
        uuid batch_id PK,FK
        uuid supplier_id FK "null while draft"
        varchar material_kind "catalog code"
        numeric10_3 weight_kg
        int quantity
        date import_date "set at Finish, null while draft"
        varchar status "draft | finished"
        uuid finished_by FK
        timestamptz finished_at
        uuid updated_by FK
        timestamptz updated_at
    }
    production_outputs {
        uuid batch_id PK,FK
        numeric10_3 wings_kg
        numeric10_3 thighs_kg
        int wings_count "computed"
        int thighs_count "computed"
        numeric10_1 marinade_g
        date production_date "set at Finish"
        varchar status
    }
    production_packaging {
        uuid batch_id PK,FK
        int big_packages
        int small_packages
        int rejected_wings
        int rejected_thighs
        text comment
        date packaging_date "set at Finish"
        varchar status
    }
    production_byproducts {
        uuid batch_id PK,FK
        varchar item_code PK "catalog code"
        numeric10_3 produced_kg
        numeric10_3 carry_kg
        numeric10_3 rejected_kg
    }
    production_batch_counters {
        date day PK
        int last_number
    }
    production_plans {
        uuid batch_id PK,FK
        int expected_big "4-piece packs"
        int expected_small "2-piece packs"
        varchar500 note
        varchar status "pending | confirmed"
        uuid confirmed_by FK
        timestamptz confirmed_at
        uuid updated_by FK
        timestamptz updated_at
    }
    notifications {
        uuid id PK
        uuid user_id FK
        varchar type "production.* | order.delivering | order.delivered | order.return_pending | order.returns_reviewed"
        varchar entity_type
        uuid entity_id "no FK"
        jsonb payload
        timestamptz created_at
        timestamptz read_at
        varchar telegram_status "pending | sent | failed | not_linked | bot_off"
        text telegram_error
        timestamptz sent_at
    }
    inventory_balances {
        varchar64 item_code PK "inventory/catalog.py"
        int count "null if not tracked, >= 0"
        numeric12_3 kg "null if not tracked, >= 0"
        timestamptz updated_at
    }
    inventory_movements {
        bigint id PK
        varchar64 item_code
        int count_delta
        numeric12_3 kg_delta
        bool kg_estimated
        varchar source "production | order | order_return (adjustment: manual items only)"
        uuid batch_id FK "orders: the batch the quantity is attributed to"
        uuid order_id FK "order / order_return movements"
        smallint step "1-3"
        bigint reversal_of FK "unique"
        text reason "reopen | cancel (adjustment reason for manual items)"
        int balance_count_after
        numeric12_3 balance_kg_after
        uuid created_by FK
        timestamptz created_at
    }
    orders {
        uuid id PK
        varchar32 code UK "OR-YYYYMMDD-NNN"
        uuid customer_id FK
        date delivery_date
        uuid driver_id FK "active staff / supervisor, null"
        text note "<= 1000"
        varchar status "created | delivering | return_pending | success | partly_returned | fully_returned | cancelled"
        varchar500 return_reason
        varchar500 cancel_reason
        int version
        uuid created_by FK
        timestamptz delivering_at "and _by; delivered_, returns_reviewed_, cancelled_ likewise"
    }
    order_boxes {
        uuid id PK
        uuid order_id FK
        varchar16 color "white | black"
        smallint position "unique per order"
    }
    order_box_items {
        uuid id PK
        uuid box_id FK
        varchar64 item_code "orderable; unique per box"
        int count "packs: > 0, xor kg"
        numeric12_3 kg "packed by-products: > 0"
        smallint position
    }
    order_return_items {
        uuid id PK
        uuid order_id FK
        varchar64 item_code "unique per order"
        int returned_count "xor returned_kg"
        numeric12_3 returned_kg
        int to_stock_count "null until reviewed"
        numeric12_3 to_stock_kg
        int to_wasted_count
        numeric12_3 to_wasted_kg
        uuid reviewed_by FK
        timestamptz reviewed_at
    }
    order_counters {
        date day PK
        int last_number
    }
    role_limits {
        varchar32 role PK "general_manager | supervisor | staff"
        int max_active "null = unlimited (not for GM), 1-999"
        uuid updated_by FK
        timestamptz updated_at
    }
    telegram_link_tokens {
        uuid id PK
        uuid user_id FK
        varchar token_hash UK "sha256"
        timestamptz expires_at "10 minutes"
        timestamptz used_at
    }
```

**Notes**

- **`role`** is a native PostgreSQL enum: roles are structural and change rarely.
- **`language`** is a `VARCHAR` validated by a Python enum, so new values need no migration.
- **`position`** is a free-text `VARCHAR(50)` job title for staff (migration `0002` widened it from 32).
  - It is normalized by `schemas.user.normalize_position`: trimmed, whitespace collapsed, case and Khmer kept.
  - It is a **label only**. Nothing in `permissions/`, `deps.py` or the services branches on its value, so it has no effect on access.
  - Only its *presence* is tied to the role: required for staff, forbidden otherwise (`ck_users_position_staff_only`).
  - `GET /users/positions` returns the distinct values for suggestions (case-insensitive grouping, most used spelling).
- **Partial unique indexes** enforce the business invariants. See FEATURES §3.
- **Role limits** (`role_limits`, migration `0008`): one row per limited role, seeded 2 / 3 / 10 (bootstrap inserts any missing row, never overwrites). CHECKs keep `max_active` null or 1–999 and never null for the general manager. The migration dropped `uq_users_single_active_gm`; `services/role_limit_service.ensure_slot` locks the role's row (`FOR UPDATE`) and counts active users inside the create / reactivate / role-change transaction, so concurrent requests for the last slot are serialized.
- **Inventory** (migration `0010`): `inventory_balances` (one row per catalog item, created at startup and on demand; CHECK `count >= 0`, `kg >= 0`) and `inventory_movements` (append-only ledger; indexes on (`item_code`, `created_at`) and `batch_id`; unique partial index on `reversal_of`, so a movement is reversed at most once). `production_batches.inventory_tracked` was added as false for every existing batch, then defaults to true. Migration `0011` (data only) removed the adjustment movements and recomputed the balances and `balance_*_after` from production (production items are read-only). Item codes have no FK: the catalog lives in code (`app/inventory/catalog.py`), like permissions and by-products.
- **Business info and delivery notes** (migration `0013`): `business_settings`, one row (`ck_business_settings_single_row`: `id = 1`; `ck_business_settings_logo_mime`: logo and its MIME type both set or both null), seeded with the business name; the logo is `bytea`, loaded only when asked for (`deferred`). `orders.print_count` (default 0) counts generated delivery notes; it isn't part of the order's `version`.
- **Orders** (`models/order.py`, migration `0012`): `orders` (code unique; `ix_orders_status_delivery_date`, `customer_id`, `driver_id` indexed), `order_boxes` (unique `order_id, position`), `order_box_items` (unique `box_id, item_code`; CHECK `count` xor `kg`, > 0), `order_return_items` (unique `order_id, item_code`; CHECKs returned > 0, split ≥ 0, and once reviewed stock + wasted = returned), `order_counters` (codes per day, like production). Boxes, lines and returns load with the order (`selectin`). The migration also added `inventory_movements.order_id` (FK, SET NULL, indexed), widened `ck_inventory_movements_source` to `order` / `order_return` and `ck_notifications_type` to the four order alerts. Item codes are the inventory codes (no FK). The wasted pack items need no migration (balance rows on demand).
- **Uniqueness only counts active users,** so a deactivated user's username can be reused.
- **`permissions` rows are never deleted.** Removing a permission from the registry flips `is_active`.
- **`suppliers` / `customers`** share their columns and indexes through `PartnerMixin` (`models/partner.py`), migration `0004`:
  - `ix_<table>_name_lower` on `lower(name)` for case-insensitive sorting and search;
  - `uq_<table>_active_phone`, a partial unique index on `phone` `WHERE is_active AND phone IS NOT NULL`: one active record per normalized number, per table;
  - `phone` stores the normalized form (digits, optional leading `+`); `phone_display` is computed on output.
- **Production** (`models/production.py`, migrations `0005`, `0006` and `0007`):
  - one `production_batches` row per batch, and **one row per step** (`production_raw_materials`, `production_outputs`, `production_packaging`, PK = `batch_id`, `ON DELETE CASCADE`). A step's row is created when it becomes available (step 1 with the batch, step 2 when step 1 is first finished, step 3 when step 2 is), so "not started" is simply a missing row. All three step tables share `status` / `finished_by` / `finished_at` / `updated_by` / `updated_at` through `StepMixin`;
  - `production_byproducts`: one row per batch and catalog `item_code` (created on demand, so a new catalog entry needs no migration);
  - **step dates** (migration `0006`): `production_raw_materials.import_date`, `production_outputs.production_date` and `production_packaging.packaging_date` (`DATE`, indexed), written by the service at Finish (today in `BUSINESS_TIMEZONE`) and cleared on reopen. A CHECK per table (`ck_<table>_<column>_matches_status`: `(status = 'finished') = (<date> IS NOT NULL)`) is the safety net. The migration filled them for finished steps from `finished_at` converted to `BUSINESS_TIMEZONE` (drafts stay null) and dropped `production_batches.production_date`; batch codes were not touched;
  - `production_batch_counters`: the last number used per creation day, incremented with `INSERT … ON CONFLICT (day) DO UPDATE … RETURNING`. The row stays locked until the transaction ends, so concurrent creations on one day get distinct numbers; `uq_production_batches_code` is the safety net;
  - CHECK constraints keep statuses, `current_step` (1–3) and all quantities ≥ 0 valid even outside the API;
  - the relationships load with `selectin`, so a batch arrives with all its steps (no lazy loads under asyncio).
- **Packaging plan** (`production_plans`, migration `0007`): one row per batch, created by `production_service` when step 2 is finished and reset to `pending` on step 2 re-finish / step 1–2 reopen. CHECKs: `status` in (`pending`, `confirmed`), values ≥ 0, and `ck_production_plans_confirmed_complete` (a confirmed plan has both values). Loaded with the batch (`selectin`). The migration created a `pending` plan for each in-progress batch whose step 2 was finished; completed and cancelled batches have none (`plan_legacy`).
- **Notifications** (`notifications`, migration `0007`): one row per recipient, indexed on (`user_id`, `read_at`, `created_at`) for the bell. `entity_type` / `entity_id` like `audit_logs` (no FK). `payload` keeps `actor_id`, turned into a `UserRef` when read. CHECKs on `type` and `telegram_status`.
- **Telegram link tokens** (`telegram_link_tokens`, migration `0007`): SHA-256 of the raw token (unique), 10-minute `expires_at`, `used_at` once consumed.
- **Weights are `Decimal` end to end:** `NUMERIC(10,3)` for kg and `NUMERIC(10,1)` for grams in the database, `Decimal` in Python (never `float`), accepted by Pydantic from JSON numbers or strings with `max_digits` / `decimal_places`, and serialized as fixed-precision strings (`"12.500"`, `"350.0"`) through a `PlainSerializer`. The UI parses them into scaled integers for exact sums.
- **`audit_logs.entity_type` / `entity_id`** (indexed together as `ix_audit_logs_entity`) reference non-user records. There is no foreign key because one column pair points into several tables; the audit listing resolves current names with one query per entity type (`ENTITY_LABELS`: `suppliers.name`, `customers.name`, `production_batches.code`, `orders.code`).
- **Constraint naming.** All constraints follow a naming convention (`ix_`, `uq_`, `ck_`, `fk_`, `pk_`), which keeps Alembic autogenerate deterministic.
- **Timestamps** are `timestamptz`. The app sets them in Python (UTC) and also has server defaults. Setting them in Python avoids lazy loads after `commit` under asyncio (`expire_on_commit=False`).

### Orders and inventory (FIFO by batch)

```mermaid
sequenceDiagram
    participant R as POST /orders/{id}/delivering
    participant O as order_service
    participant I as inventory_service
    participant DB as PostgreSQL

    R->>O: start_delivery(version)
    O->>DB: SELECT order FOR UPDATE (status, version)
    O->>I: take_for_order(totals per item)
    I->>DB: lock balances FOR UPDATE (item_code order)
    I->>DB: per item: each batch's net (sum of its movements), oldest batch first
    I->>DB: apply_movements: one −movement per (item, batch), order_id set
    O->>DB: status delivering, audit, notifications
    O->>DB: COMMIT
```

- **Attribution:** every movement of a production item carries a `batch_id`; a batch's contribution to an item is the **sum of its movements, any source**. Delivering spends the oldest batches' contributions first; the review gives back to the batches the order took from, newest first (stock first, then wasted into the wasted item of the same batch). So `item_detail`'s per-batch sources always add up to the balance.
- **Guard in `reverse`:** before writing a production reversal, the batch's own contribution per item must cover the net it removes; otherwise `PRODUCTION_STOCK_ALREADY_USED` with the order codes (from the order movements with that `batch_id`).
- **Locking:** both paths lock the affected balance rows **before** reading contributions. Any change to an item's movements takes that lock, so the read is consistent until commit. Lock order is unchanged: the batch / order row first, then balances in `item_code` order (an order and a batch are never locked together).
- **Warnings vs. errors:** create and edit only compute `stock_warnings` (not locked); the hard check is at Delivering (`INVENTORY_INSUFFICIENT`, nothing written).
- **Units:** inside the services a quantity is one `Decimal` in the item's unit (count or kg); `_qty_delta` turns it into a count or kg movement. Packs stay whole numbers.

### Documents (delivery notes)

```mermaid
sequenceDiagram
    participant C as Client
    participant R as GET /orders/{id}/document.pdf
    participant D as document_service
    participant DB as PostgreSQL
    participant W as worker thread (WeasyPrint)

    C->>R: Bearer token
    R->>D: print_order(order_id, via=download)
    D->>DB: UPDATE orders SET print_count = print_count + 1 RETURNING (locks the row)
    D->>D: OrderOut (redacted for the viewer) + business info → build_context (COPY #n if n > 1)
    D->>W: render_pdf (≤ 2 at once, 20 s timeout)
    W-->>D: PDF bytes
    D->>DB: audit order.document_printed
    R->>DB: COMMIT
    R-->>C: application/pdf (inline, <code>.pdf)
```

- **Template:** `documents/templates/delivery_note.html.j2` + `receipt.css`, Jinja2 with autoescape. `build_context` (pure Python, no WeasyPrint) turns the order **as serialized for the requester** into the template's context, so user names are already redacted. Labels are Khmer with English under them (`LABELS`); items use short names ("Liver", not "Liver (packed)").
- **Fonts:** Kantumruy Pro (SIL OFL) as two static instances (Regular 400, Bold 700) cut from the Google Fonts variable font with fontTools, loaded by `@font-face` from `documents/fonts/`. Nothing is fetched at runtime; Pango + HarfBuzz shape the Khmer. DejaVu Sans (image package) is the fallback for any glyph the font lacks.
- **Height fits the content (two passes):** pass 1 renders on an 80 × 3000 mm page and reads the bottom of the empty `#end` element from WeasyPrint's layout boxes; pass 2 renders at that height + the bottom margin (at least 60 mm). A note longer than the probe page keeps the probe's pages.
- **Off the event loop:** `anyio.to_thread.run_sync` with a `CapacityLimiter(2)` and `fail_after(20)` (`abandon_on_cancel`: the request returns 503 while the thread finishes). WeasyPrint is imported lazily (`render.unavailable_reason()`), so the API starts and everything else works where its system libraries are missing (plain Windows); documents then answer `503 DOCUMENT_UNAVAILABLE`.
- **Counting:** the atomic `UPDATE … RETURNING` both numbers the note and locks the order row until commit, so concurrent prints get distinct numbers (one original). The order's `version` is untouched. A failed render or Telegram send rolls back: nothing counted, nothing audited.
- **Telegram:** `notify.api_bot(runtime)` is the one place deciding which bot the API sends with (shared with `deliver`); `send_document` posts a `BufferedInputFile` to the requester's `telegram_user_id` with a 30 s request timeout.
- **Black and white:** the stylesheet uses only `#000` / `#fff` (a test checks it); box colours are a filled or outlined square plus the name.
- **Prices later:** `DocumentKind` (`DELIVERY_NOTE`, `INVOICE`) holds the title and `show_prices`; `kind_for(order)` is the single switch. The template's price columns and money total already exist behind `kind.show_prices`.
- **Docker:** the image installs `libpango-1.0-0`, `libpangoft2-1.0-0`, `libharfbuzz-subset0`, `libfontconfig1` and `fonts-dejavu-core`.
- **Business info** (`services/business_service.py`): `get_row` recreates the single row with the default names if it's missing; the logo is decoded with Pillow (PNG / JPEG only, ≤ 500 kB, ≤ 25 megapixels before decoding) and stored resized to ≤ 400 px wide.

## 6. Authorization model

Authorization combines **two independent axes**, plus a **feature layer** on top of permissions for general managers (and, for staff, supervisors with Staff access):

**The superadmin can do everything the general manager can.** It holds every permission implicitly, manages every other role, and every `require_role(...)` that lists `general_manager` also lists `superadmin` (the audit log). Role checks on `general_manager` in services are business rules (one active GM), never access checks. `tests/test_superadmin_superset.py` enforces this for every route, including future ones (§12).

```mermaid
flowchart LR
    Q{Can actor do X<br/>to target?}
    Q --> A["WHAT: permission<br/>require_permission(code)<br/>from user_permissions<br/>(superadmin: all)"]
    Q --> B["WHO: role hierarchy<br/>ensure_can_manage(actor, target)<br/>MANAGEABLE_ROLES"]
    A --> OK((allowed))
    B --> OK
```

| Layer | Where | Answers |
|---|---|---|
| `require_permission(*codes)` | `deps.py` | Does the actor hold the feature permission? |
| `require_any_permission(*codes)` | `deps.py` | At least one of them (the Access endpoints: `permissions.grant` or `users.manage_access`) |
| `require_role(*roles)` | `deps.py` | Coarse role gate, e.g. the audit log |
| `ensure_can_manage(actor, target)` | `permissions/hierarchy.py` | Is the target strictly below the actor? |
| `ensure_can_manage_role(actor, role)` | `permissions/hierarchy.py` | Can the actor create or filter this role? |
| Detailed grant rules | `permissions/service.py` | Superadmin only (`require_role`). Held-by-grantor, `grantable_by`, target active, `assignable_to` |
| Feature levels | `permissions/features.py` | GM and superadmin: set Off / View only / [Record /] Full access; supervisor with Staff access: staff only, capped by its own access; diff within the feature's codes |
| Redaction | `services/redaction.py`, `schemas/common.py` | Hides the superadmin from every other viewer |

### How effective permissions are computed

```sql
SELECT up.permission_code
FROM user_permissions up JOIN permissions p ON p.code = up.permission_code
WHERE up.user_id = :uid
  AND p.is_active
  AND :role = ANY(p.assignable_to)
```

The superadmin short-circuits to "all active permissions".

### Grant rule order

Detailed permissions are the superadmin's tool: the four endpoints are guarded by `require_role(superadmin)`. Behind that guard, `block_reason(actor, actor_perms, target, perm)` returns the first failing rule, and both the grant/revoke endpoints and the permission matrix (`can_edit` + `reason`) use it:

| # | Rule | Error |
|---|---|---|
| 1 | Actor holds `permissions.grant` (route guard) | `MISSING_PERMISSION` |
| 2 | Target is in the actor's scope | `FORBIDDEN_SCOPE` |
| 3 | Permission exists and is active (endpoints only) | `PERMISSION_NOT_FOUND` |
| 4 | Actor holds the permission (grant and revoke) | `PERMISSION_NOT_HELD` |
| 5 | `grantable_by[target.role]`, if present, lists the actor's role (grant and revoke; superadmin exempt) | `PERMISSION_GRANT_RESTRICTED` |
| 6 | Grant only: target is active | `USER_INACTIVE` |
| 7 | Grant only: target's role is in `assignable_to` | `PERMISSION_NOT_ASSIGNABLE` |

`grantable_by` refines *who may hand out* a permission for particular target roles, without touching the role hierarchy. No permission uses it now (it used to keep partner permissions away from staff unless the superadmin granted them); the mechanism stays. Features can't contain such permissions (startup validation), because a level change doesn't apply per-permission grant rules.

### Feature layer

```mermaid
flowchart LR
    GM[General manager<br/>Access tab] -->|PUT /users/{id}/features/{f}| F[features.set_level]
    SUP[Supervisor with Staff access<br/>Access tab of staff] -->|same, capped| F
    SA[Superadmin<br/>Permissions (advanced)] -->|PUT/DELETE /users/{id}/permissions/{code}| G[service.grant / revoke]
    F -->|diff: insert / delete<br/>only the feature's codes| UP[(user_permissions)]
    G --> UP
    UP -->|effective permissions| ME[/auth/me → menus, guards/]
```

- A feature (`registry.FEATURES`) maps each level to an exact set of codes. Levels come from `LEVELS = (off, view, record, full)` in that order; a feature starts with `off` and may omit any of the others (`production` and `staff_management` have `record` = view + create; `staff_access` is only `off` / `full`). `current_level` = the level whose set equals the user's effective codes within the feature, else `custom`; this works unchanged for any number of levels.
- `set_level` checks, in order: scope (`FORBIDDEN_SCOPE`; the hidden account is already `USER_NOT_FOUND`), `FEATURE_NOT_FOUND`, `FEATURE_NOT_APPLICABLE`, unknown level (`VALIDATION_ERROR`), the supervisor cap (`PERMISSION_NOT_HELD`), target active (`USER_INACTIVE`). The level is a plain string in the body so this order holds.
- **Two kinds of grantor.** Whoever holds `permissions.grant` (general managers, the superadmin) sets any level of any applicable feature: no held-by-grantor rule. Whoever holds `users.manage_access` but not `permissions.grant` (a supervisor with Staff access) is **capped**: `allowed_levels(feature, actor_perms)` keeps only the levels whose codes are all in the actor's effective permissions, and `set_level` refuses the rest. The same function fills `allowed` on every level in `GET /users/{id}/features`, so the UI and the endpoint can't disagree. Scope limits supervisors to staff. There is no cascade: lowering a supervisor leaves the staff levels it set.
- **Features a grantor must hold** (`FeatureDef.grantor_must_hold`, e.g. `inventory_history`): `visible_to(feature, actor_perms)` is true only when the actor holds every code of the feature (the superadmin always does). `feature_matrix` skips invisible features, `set_level` answers `FEATURE_NOT_FOUND` for them at the "feature exists" step (before scope-independent checks such as the target role, so nothing leaks), and `audit_service.list_audit_logs` hides their `feature.set` entries (`details->>'feature'`) from viewers for whom `hidden_features(perms)` lists them. Unlike the supervisor cap this applies to general managers too; there is no cascade.
- `users.manage_access` is supervisor-only (`assignable_to`), so `grant_defaults` treats a creator holding `permissions.grant` as holding it; otherwise a GM-created supervisor would miss its default Staff access.
- **Role changes** (`user_service.change_role`) call `service.reset_to_role_defaults`: all grants are replaced by `DEFAULT_PERMISSIONS[new role]` (not limited to what the actor holds), in the same transaction as the role update and the `user.role_change` audit entry.
- The diff touches only the feature's codes, in one transaction, with one `feature.set` audit entry and no `permission.*` entries. Re-setting the current level writes nothing.
- `DEFAULT_PERMISSIONS` for supervisors and staff is computed from feature levels (supervisor: workstation Full except the production plan, Staff management View only, Staff access Full; staff: all Off).
- **Changing a default for existing users** is a data migration, not a startup step: `0009_supervisor_staff_defaults` moved supervisors at exactly Full staff management to View only, with a `feature.set` entry (`source = "default_change"`, no actor) per user. Alembic records that it ran, so it's idempotent without a flag, and it runs before the registry sync and backfill.

The query filters on `is_active` and `assignable_to` **at read time**, not only when a grant is made. So if a registry change deactivates a permission or narrows its `assignable_to`, existing grants stop working immediately, with no data migration. That's how supervisors lost `permissions.grant` and `users.delete`: the rows remain, the effect is gone.

## 7. Authentication internals

### 7.1 Token design

```mermaid
sequenceDiagram
    participant UI
    participant API
    participant DB
    UI->>API: POST /auth/login
    API->>DB: verify argon2, reset counters, INSERT refresh_tokens(hash)
    API-->>UI: access (JWT 15m) + refresh (raw, 7d)
    Note over UI: …15 minutes later…
    UI->>API: GET /users (expired JWT)
    API-->>UI: 401 TOKEN_EXPIRED
    UI->>API: POST /auth/refresh (raw refresh)
    API->>DB: SELECT … WHERE token_hash=sha256(raw) FOR UPDATE
    API->>DB: revoked_at=now, INSERT new token, replaced_by=new.id
    API-->>UI: new pair
    UI->>API: retry GET /users
```

- **Stateless access tokens:** no database hit to validate the signature. The user row is still loaded on each request to check `is_active` and `must_change_password`.
- **Refresh tokens:**
  - **Hashing.** They are hashed with SHA-256 rather than argon2: they are high-entropy random values, so a fast hash is enough, and it lets them be looked up by an indexed equality match.
  - **Row lock.** `SELECT … FOR UPDATE` prevents double-spending one token under concurrent refreshes.
  - **Mass revocation** is a single `UPDATE … WHERE user_id = … AND revoked_at IS NULL`. It runs on deactivation, password reset and "log out everywhere".

### 7.2 Lockout

- **Race handling.** The login flow selects the user `FOR UPDATE`, so concurrent attempts are serialized per account.
- **Commit before rejecting.** The failure count and lock are committed *before* the error is raised, so a rejected login still persists its side effects.

### 7.3 Telegram initData

`core/telegram_auth.validate_init_data` is a pure function, unit-tested with generated payloads:

1. Parse the query string strictly.
2. Pop `hash`.
3. Build `data_check_string` from the sorted `key=value` pairs, joined by `\n`.
4. `secret = HMAC_SHA256(key="WebAppData", msg=bot_token)`.
5. Compare `HMAC_SHA256(secret, data_check_string)` against `hash` in constant time.
6. Check that `auth_date` is fresh, then parse `user`.

## 8. Startup and bootstrap

```mermaid
flowchart LR
    A[container start] --> B[alembic upgrade head]
    B --> C[python -m app.bootstrap]
    C --> D[uvicorn app.main:app]
    D --> E[lifespan: bootstrap again<br/>idempotent]
```

`bootstrap()` does five things:

1. `SELECT pg_advisory_xact_lock(815001)`: serializes concurrent starts, for example several workers or replicas, or the api and a migration job.
2. `validate_features()` (also at import) and `sync_registry()`: checks FEATURES against PERMISSIONS, then upserts the registry (including `grantable_by`) and deactivates entries that were removed. It returns the codes it **inserted**.
3. `backfill_defaults(new_codes)`: grants each newly inserted permission to every active user whose role has it in `DEFAULT_PERMISSIONS` (`granted_by = NULL`, `INSERT … ON CONFLICT DO NOTHING`), with a `permission.grant` audit entry per grant (`details.source = "default_backfill"`). Because it only sees codes inserted by this run, it grants nothing on later starts, and a manual revoke stays revoked.
4. `seed_superadmin()`: creates the superadmin if none exists, with `must_change_password = false`.
5. **Webhook registration**, only when `BOT_MODE=webhook`, a token is set and `TELEGRAM_WEBHOOK_AUTO_SET=true`. `ensure_webhook()`:
   1. calls `getWebhookInfo`;
   2. calls `setWebhook(url, secret_token, allowed_updates=dp.resolve_used_update_types(), drop_pending_updates)` and `setMyCommands` only if **any** of these differ:
      - the URL;
      - the allowed updates;
      - the fingerprint stored in `app_settings`, a SHA-256 of URL, secret, allowed updates and drop-pending. Telegram never returns the secret, so this is the only way to detect a rotated secret.
   - Every Telegram call has a 10 s timeout. **Any failure is logged and swallowed**, so the API still comes up.
   - Because this runs under the advisory lock, several workers starting together register once. The rest see the matching fingerprint and skip.

It then commits. The whole thing is idempotent.

- It also runs inside the FastAPI lifespan, so a plain `uvicorn` run in development gets the same guarantees.
- The lifespan creates the `TelegramRuntime` first (webhook mode only) and passes it in, so registration and request handling use the same `Bot` and `Dispatcher`.
- When run as `python -m app.bootstrap`, a short-lived `Bot` is created for registration and then closed.

## 9. Telegram bot

### 9.1 Webhook mode (default)

```mermaid
sequenceDiagram
    participant T as Telegram
    participant W as POST /api/telegram/webhook
    participant D as Dispatcher (app.state.telegram)
    participant H as handlers
    participant DB as PostgreSQL

    T->>W: Update JSON + X-Telegram-Bot-Api-Secret-Token
    alt no runtime (polling / off / no token)
        W-->>T: 404
    else secret mismatch or missing
        W-->>T: 401 (warning logged, body not read)
    else
        W->>D: Update.model_validate → feed_update(bot, update)
        D->>H: /start or /lang
        H->>DB: short-lived session (language, bot_prefs)
        H->>T: sendMessage (via the same Bot)
        W-->>T: 200 (also when a handler raised: logged, not retried)
    end
```

- **Lifecycle.** The FastAPI lifespan builds one `TelegramRuntime` per process: a `Bot` and a `Dispatcher` from `bot/setup.py`. It is stored on `app.state.telegram`, and the bot's HTTP session is closed on shutdown.
- **The endpoint** lives outside `/api/v1`: it isn't part of the versioned public API. It is still under `/api`, so the Vite dev proxy and a same-origin production setup both reach it through one HTTPS domain.
  - It is hidden from OpenAPI and uses no auth dependencies. It is authenticated only by the secret token, compared with `hmac.compare_digest`.
- **Inline processing.** Updates are handled inline in the request, with no background queue. Handlers are short (one database session each), well within Telegram's timeout.
- **Handlers** (`bot/handlers.py`) are stateless and are registered only in `create_dispatcher()`. `create_router()` returns a fresh router each time, because an aiogram router can only have one parent.
- **Shared data.** The bot reuses `app.db.SessionLocal` and the models: there is one source of truth for users and their language.
- **Bot texts** live in `bot/i18n.py`, separately from the UI translations.

### 9.2 Polling mode (fallback for local development)

- `BOT_MODE=polling` + `python -m app.bot` (compose: `docker compose --profile polling up`).
  - It deletes any registered webhook, clears the stored fingerprint, sets the commands, then long-polls with the **same** `create_dispatcher()`.
  - In this mode the API creates no runtime, so the webhook endpoint returns 404 and nothing is registered at startup.
- The whole stack must use `BOT_MODE=polling`. If the API still runs in webhook mode, it re-registers the webhook on its next restart, and Telegram then rejects `getUpdates`. The poller logs a warning when it finds a webhook registered.
- **Only one polling instance** per bot token may run: Telegram rejects concurrent `getUpdates` calls.

### 9.3 Sending from the API (production and order alerts)

```mermaid
sequenceDiagram
    participant C as Client
    participant R as POST /production/{id}/produced/finish
    participant S as production_service
    participant DB as PostgreSQL
    participant B as BackgroundTasks → bot/notify.deliver
    participant T as Telegram

    C->>R: {version}
    R->>S: finish_step
    S->>DB: finish step, create plan, INSERT notifications (one per recipient), audit
    S->>DB: COMMIT
    R-->>C: 200 batch
    R->>B: deliver(ids, app.state.telegram)
    B->>DB: own session: load rows + recipients
    B->>T: sendMessage per linked recipient (inline web_app button)
    B->>DB: telegram_status sent / failed / not_linked / bot_off
```

- **Same path for orders:** Delivering, Delivered and the return review call `notify(..., permission="orders.review_returns")` in their transaction; the orders router hands the queued ids to the same `deliver` task. `notify` takes the recipients' permission (`production_plan.view` by default), so a new alert family needs no new plumbing; `message_for` picks the text and the button (`/workstation/orders/<id>`) by type.
- **Stored first, sent after commit.** `notification_service.notify()` adds the rows in the Finish transaction and queues their ids on the session (`session.info`); the router takes them (`take_queued`) and hands them to a FastAPI background task, which runs after the response with its own session. A rolled-back Finish sends nothing (`discard_queued`).
- **Which bot:** webhook mode uses the runtime's `Bot` (`app.state.telegram`); polling mode creates a short-lived `Bot` (`notify.bot_factory`) because the poller is another process; no token / `BOT_MODE=off` / no runtime → `bot_off`.
- **Never fails the action:** every exception is caught, logged and recorded as `failed` (with the error). There is no retry loop; `python -m app.bot notifications resend-failed` retries the failed rows once with a short-lived bot.
- **Texts** live in `bot/i18n.py` (km/en, HTML; the code and comment are escaped). The bot username for the superadmin's link comes from `getMe`, cached per process (`notify.bot_username`).

### 9.4 Scaling

In webhook mode the API can run **multiple uvicorn workers or replicas**.

- Each worker has its own `Bot` and `Dispatcher`, and Telegram delivers each update to whichever worker the load balancer picks.
- Handlers keep no in-process state, so no coordination is needed.
- Startup registration is serialized by the bootstrap advisory lock (§8).

## 10. Error handling

- Domain errors are raised as `AppError(status, ErrorCode, message, details)`.
- Handlers in `core/errors.py` map these to JSON:

  | Raised | Response |
  |---|---|
  | `AppError` | `{"error": {"code", "message", "details?"}}` |
  | `RequestValidationError` | `422 VALIDATION_ERROR`, with `details.fields[] = {loc, type, msg}` |
  | Starlette `HTTPException` | `NOT_FOUND`, `METHOD_NOT_ALLOWED` or `HTTP_ERROR` |

- **Database constraint violations become API errors.** `_flush_or_conflict` in `user_service` catches `IntegrityError` and maps the name of the violated partial unique index to a domain code (`DUPLICATE_TELEGRAM_USERNAME`). The old single-GM mapping (`GM_ALREADY_EXISTS`) is gone with its index; role limits are checked under a row lock instead (§5).
  - The code also checks these conditions up front, for friendly errors.
  - The database index is the real guarantee under concurrency.

## 11. Configuration

- **Source:** all settings live in `app/config.py` (`Settings`).
- **Where values come from:** environment variables first, then `.env`.
- **Access:** through the cached `get_settings()`.
- **Required:** `JWT_SECRET`. In webhook mode with a bot token, also `TELEGRAM_WEBHOOK_URL` and `TELEGRAM_WEBHOOK_SECRET`.
- **Full list:** in the README.

**API docs**

| Setting | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `development` | Set `production` in production. |
| `API_DOCS_ENABLED` | unset | `true` / `false` forces `/docs`, `/redoc`, `/openapi.json` on or off. Unset: on only when `ENVIRONMENT=development`. The schema lists every role, so it stays off in production. |

**Business settings**

| Setting | Default | Notes |
|---|---|---|
| `BUSINESS_TIMEZONE` | `Asia/Phnom_Penh` | IANA zone for business calendars, e.g. the "new this month" figure on suppliers and customers. Validated at startup. Zone data comes from the `tzdata` package, so it works on Windows and slim images too. |

**Telegram bot settings**

| Setting | Default | Notes |
|---|---|---|
| `BOT_MODE` | `webhook` | `webhook` \| `polling` \| `off` |
| `TELEGRAM_WEBHOOK_URL` | empty | Full public URL, e.g. `https://example.com/api/telegram/webhook`. Must be `https` on port 443, 80, 88 or 8443. |
| `TELEGRAM_WEBHOOK_SECRET` | empty | 1–256 chars `[A-Za-z0-9_-]`. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. |
| `TELEGRAM_WEBHOOK_AUTO_SET` | `true` | Register or refresh the webhook during bootstrap. |
| `TELEGRAM_DROP_PENDING_UPDATES` | `false` | Passed to `setWebhook`. |

**Startup validation.** A `model_validator` on `Settings` checks the URL and secret whenever `webhook_enabled` is true (webhook mode and a token is set).

- A misconfigured deployment fails at startup with a clear message, rather than silently never receiving updates.
- Every entry point that loads settings fails this way, including Alembic and the CLI.
- With `polling` / `off`, or with no token, the webhook values are not checked.

Settings are read at import time by `app.db` to build the engine. Tests therefore set environment variables at the top of `tests/conftest.py`, *before* importing `app`.

## 12. Testing strategy

| Aspect | Approach |
|---|---|
| Database | A real PostgreSQL (`TEST_DATABASE_URL`). The partial indexes, `ANY(array)` and `FOR UPDATE` are Postgres-specific. |
| Schema | A session fixture drops the `public` schema, then runs **Alembic `upgrade head`**. This tests the migration too. |
| Isolation | Before each test: `TRUNCATE … RESTART IDENTITY CASCADE`, then `bootstrap()`. |
| Engine | `DB_NULL_POOL=true` avoids connection reuse across pytest-asyncio event loops. |
| HTTP | `httpx.AsyncClient` over `ASGITransport(app)`: in-process, no server. |
| Auth in tests | `auth(user)` mints an access token directly. Login flows have their own tests. |
| Coverage focus | Scope matrix for every role pair; grant rules; defaults; DB invariants; forced password change; lockout; Telegram valid / tampered / expired / binding; normalization; deactivation; resets; audit access; webhook secret / dispatch / errors / modes; webhook registration; bot settings validation; default backfill, `grantable_by` and `reason`; suppliers/customers CRUD, validation, phone rules, duplicates, search/sort/paging, stats month boundary, audit entities (parametrized over both lists); feature levels (mapping, diffs, check order, defaults, startup validation); detailed permissions superadmin-only; **superadmin invisibility sweep** over every GET route from the OpenAPI schema plus key mutations, as GM / supervisor / staff; **superadmin ⊇ GM sweep** (`test_superadmin_superset.py`): every route and method in the schema is called as the GM and, wherever the GM isn't refused with 403, as the superadmin, which must not get 403 either (placeholders filled with targets both manage; empty bodies unless a valid one is needed to reach a service-level check; both accounts reset between calls); production steps, drafts, versions, reopen (cascading), cancel (GM only), codes under concurrency, stats; GM feature levels set by the superadmin; packaging plan (feature and backfill, lifecycle through reopen sequences, pieces rule, confirm, lock, versions, cancelled, legacy batches, audit, list and detail) and the step 3 gate and comment rule; notifications (recipients by permission, rows only with a successful Finish, Telegram per language with the web_app button, `not_linked` / `bot_off` / `failed`, polling-mode bot, repeat after reopen, resend, own-only bell, "System" actor); superadmin Telegram link (hashed single-use token, expiry, id taken, unlink, role guard); role limits (defaults, create / reactivate / role change at the limit per role and actor, freed slots, unlimited, range, lowering below the count, superadmin-only settings and hidden audit, capacity per viewer, two GMs out of each other's scope and both alerted) including **concurrent creates for the last slot** (several requests at once, each with its own session: exactly one succeeds; the test fails without the row lock); supervisors setting staff access (scope, cap, `allowed`, no cascade, Staff access Off) and View / Record / Full staff management; migrations `0006`, `0007`, `0008`, `0009` (idempotent), `0010` and `0011` (reset, idempotent); inventory (movements per Finish incl. estimated waste kg and the by-product split, two batches, reopen cascades latest first, re-finish, cancel, no double reversal, negative guard on Finish / reopen / cancel with nothing changed, untracked batches, production items refused for everyone, per-batch breakdown through step 3 / reopen / cancel adding up to the balance, access and backfill, history filters, concurrent Finishes on the same items); inventory history (Off by default, movements and batch stock changes gated, grantor-must-hold: superadmin on GMs and supervisors, a GM only while holding it, hidden in GET / 404 on PUT / hidden audit entries, no cascade); orders (`test_orders.py`: registry levels and defaults, backfill, staff Off / View only, supervisor cap for staff Orders, staff Record without edit / review; create with boxes and the per-colour summary, every validation location, colours and extra fields, customer / driver rules, edit with box replacement and audit diff, conflicts, edit / cancel only Created and only with their permission; Delivering FIFO across two batches with the per-batch breakdown and order movements, `INVENTORY_INSUFFICIENT` keeping it Created, version conflict; Delivered accepted / returned validation; review split, stock / wasted movements attributed newest first, partly vs fully returned, wasted by-products; the **production guard** on reopen of step 3 and of step 2 (cascade), allowed for an untouched batch and after a return to stock, still blocked after a return to wasted; codes under concurrency; stats and list filters; available stock; audit entity names); order alerts (`test_order_notifications.py`: recipients = holders of `orders.review_returns`, one row per status change, payloads, none on a failed Delivering, the bell, Khmer Telegram texts with the **Open order** button, English texts escaped); migration `0012` round trip. The redaction and superset sweeps fill `{order_id}`; delivery notes (`test_documents.py`: content per status (Created, Delivering, Return pending, reviewed, Success, Cancelled banner), COPY numbering and `order.document_printed` audit, version untouched, access, "System" for the superadmin, renderer unavailable → 503 with nothing counted, Telegram send to the linked chat (`SendDocument`, escaped caption, QR) / not linked / bot off / Telegram failing with nothing counted, invoice switch and black-and-white stylesheet; with WeasyPrint: real PDFs 80 mm wide, Khmer and English text extracted with pypdf, a longer order gives a taller page, the preview PDF); business info (`test_business_info.py`: seeded row, superadmin edits, GM only with the feature, not applicable to supervisors, validation, phone normalization, logo resize / kept as uploaded / wrong type / empty / over 500 kB / remove, audit, preview data source). Route tests use the `html_documents` fixture (the renderer returns the template's HTML), so counting, audit and **redaction** are checked as text and run anywhere; the redaction sweep reads the notes, and the superset sweep gives its GM Business info so the settings routes are compared. |
| PDFs | The `needs_weasyprint` tests are **skipped where WeasyPrint's system libraries are missing** (a plain Windows machine). Run the full suite in the API image to cover them: build the image, add the dev dependencies (`FROM <image>` + `RUN uv sync --frozen`), mount the repo and run `/app/.venv/bin/python -m pytest` with `TEST_DATABASE_URL` pointing at the test database. Put the test container and the test Postgres on **one Docker network** and use the container name as host: through `host.docker.internal` (Docker Desktop's port forwarding) a few of the thousands of new connections (`DB_NULL_POOL`) time out, which shows up as random `TimeoutError`s. |
| Telegram | Never contacted. Alert tests put a runtime with a `RecordingSession` bot on `app.state` (webhook mode) or replace `notify.bot_factory` (polling); background tasks finish before the in-process request returns, so assertions see the final `telegram_status`. `tests/telegram_fakes.RecordingSession` is an aiogram `BaseSession` that records Bot API calls (`SendMessage`, `SetWebhook`, …) and returns canned responses, or simulates an outage. `BOT_MODE=off` by default; webhook tests put their own `TelegramRuntime` on `app.state`. |

Run:

```bash
uv run pytest
```

Lint and format:

```bash
uv run ruff check . && uv run ruff format --check .
```

## 13. Deployment

- **Image:** one image (`Dockerfile`, `python:3.12-slim` + uv, frozen lockfile, no dev dependencies) serves both the `api` and the optional `bot-polling` service. It also installs WeasyPrint's system packages (Pango, HarfBuzz, fontconfig, DejaVu fonts) for delivery note PDFs.
- **Default stack** (`docker compose up`): `postgres` + `api`.
  1. `postgres` becomes healthy.
  2. `api` runs migrations and bootstrap (including webhook registration), then becomes healthy on `/health`.
- **Polling profile** (`docker compose --profile polling up`, with `BOT_MODE=polling` in `.env`): adds `bot-polling`, which starts after `api` is healthy.
- **Network:** the `api` container needs **outbound HTTPS to `api.telegram.org`** (for `setWebhook`, `sendMessage` and `sendDocument`), and **inbound HTTPS from Telegram** on the public URL.
- **Production notes:**
  - Put the API behind a TLS-terminating reverse proxy that forwards `/api/*`, including `/api/telegram/webhook`.
  - Serve the UI on the same origin under `/`, and the API under `/api`. Otherwise configure `CORS_ORIGINS`.
  - Use a strong `JWT_SECRET`. Rotating it invalidates all access tokens; refresh tokens keep working.
  - Rotating `TELEGRAM_WEBHOOK_SECRET` needs no extra step: the next start detects the new fingerprint and re-registers.
  - Scaling: see §9.4. Webhook mode supports multiple workers or replicas; polling mode must stay single-instance.
  - `.env` is read only when a container is **created**. After changing it, use `docker compose up -d --force-recreate <service>`, not `restart`.

## 14. Extending the system

To add a business feature, for example `orders`:

1. **Registry:** add a `ModuleDef` and `PermissionDef`s (with `assignable_to`) to `permissions/registry.py`, **and a `FeatureDef`** in `FEATURES` (`menu`, `applies_to`, levels `off` / `view` / `full` → codes) so general managers can switch it on the Access tab. `menu` is `"workstation"` for day-to-day work (e.g. `FeatureDef(code="orders", menu="workstation", …)`) or `"settings"` for administration; a new menu goes into both `Menu` and `MENUS` (the display order). Startup validation checks the feature against the permissions. Update `DEFAULT_PERMISSIONS` (supervisor/staff defaults are built from feature levels). There is no migration for permissions.
2. **Models and migration:** add the feature's tables in `models/`, then:
   ```bash
   uv run alembic revision --autogenerate -m "orders"
   ```
3. **Service and router:** add the service in `services/` and the router in `api/`. Every user reference in a response must be a `schemas.common.UserRef`, and per-user lookups must pass the viewer (`get_user_or_404(session, id, actor)`), so the superadmin stays hidden (the redaction sweep test will catch misses). Guard the routes with `require_permission("orders.view")`. Call `ensure_can_manage` whenever acting on another user's data. Record audit entries for sensitive actions.
   - **New permissions reach existing users automatically** when you list them in `DEFAULT_PERMISSIONS`: the next start backfills them (§8).
   - To keep a permission away from some roles unless a specific role grants it, set `grantable_by`.
4. **Tests:** permission denied, scope, and the happy path.

**Pattern: several lists with the same shape.** Suppliers and customers are one implementation:

- `models/partner.py`: `PartnerMixin` declares the columns and per-table indexes; `Supplier` and `Customer` only set `__tablename__`.
- `services/partner_service.py`: every rule takes a `PartnerKind(model, entity, prefix, not_found)`.
- `api/partners.py`: `build_router(kind)` creates the seven routes, guarded by `<prefix>.view|create|update|delete`.
- `tests/test_partners.py` runs every test against both kinds.

A third list with the same fields needs a model class, a `PartnerKind`, a router mount, the registry entries, a migration and translations.
5. **UI:** route guard, menu entry, `<Can>`, translations. See the UI's ARCHITECTURE.md.

**Inventory items** follow the production catalog: a new by-product gets its processed / packed / wasted items in `app/inventory/catalog.py` automatically (balance rows are created at the next start or on demand). Another kind of stock item is an `ItemDef` there, plus movements in `inventory_service.step_deltas`.

**Adding a by-product or a raw material kind** (production): add a `ByproductDef` (code, names, unit, order) or a `MaterialKindDef` (code, names, wings / thighs per unit) to `app/production/catalog.py`. No migration: by-product rows are keyed by `item_code` and created on demand, and every batch response carries the catalog, so the UI shows the new row automatically (add a `production.materialKinds.<code>` label in the UI locales if you want a translated kind name). Existing finished batches simply have no row for the new item; the new item becomes required at the next Finish of step 2 / step 3.

**Adding a feature level:** levels are the fixed ordered list `LEVELS` in `registry.py`; a feature lists the ones it uses (e.g. production uses `record`). A new level name needs an entry in `LEVELS`, in the UI's `FeatureLevel` type and `access.levels.<name>` translations.

## 15. Design decisions

| Decision | Rationale |
|---|---|
| Permissions defined in code, mirrored to the database | Code review covers every permission change, deployment is reproducible, and the database still supports foreign keys and grant history. |
| Role hierarchy separate from permissions | Keeps "who" (organizational structure) and "what" (features) orthogonal, so each can change independently. |
| Invariants in database indexes, not only in code | Race-proof: two concurrent "create GM" requests cannot both succeed. |
| Uniqueness only among active users | Supports "deactivate and recreate" without renaming old records. |
| Role change resets access to the new role's defaults | A promoted or demoted user never keeps access meant for the old role (leftover rows would silently come back if the role changed again). A general manager fine-tunes afterwards with feature levels. |
| Reload the user on every request | Deactivation and forced password change take effect instantly. The cost is one primary-key lookup. |
| Opaque, hashed, rotating refresh tokens | A database leak doesn't expose usable tokens, and each token can be revoked individually. |
| No cascade on revoke | Predictable behavior. Follow-up is surfaced through the audit log instead of silently removing other people's access. |
| Superadmin is implicit-all | New features are immediately available to the superadmin without extra grants. |
| Stable error codes, English message | The UI owns translation, and API consumers get a machine-readable contract. |
| One image for api and bot | Shared models and config, with no version drift between the API and the optional polling process. |
| Webhook in FastAPI instead of a polling process | One process fewer to deploy and monitor. It scales with the API's workers and replicas, where polling allows only one instance. Updates arrive over the same HTTPS domain as the UI and API. Telegram pushes updates instead of the bot holding a long poll open. Polling stays available as a local-dev fallback, using the same dispatcher setup. |
| Webhook fingerprint stored in the database | `getWebhookInfo` can't reveal the secret. A SHA-256 fingerprint in `app_settings` detects secret changes without calling `setWebhook` on every start. |
| Feature levels also for the GM, set by the superadmin | The superadmin controls the GM with the same simple levels the GM uses for its team, instead of permission codes. The role scope (only the superadmin manages the GM) keeps the GM from changing its own access with no extra rule. GM-only powers stay detailed permissions, so a level change can't grant or remove them by accident. |
| Reopening a finished step reopens every later step | Later steps were computed from the earlier one (counts, balances). Reopening them together, with values kept, is one action for the user and guarantees they are checked again, instead of a chain of reopen clicks in reverse order. |
| Step dates recorded by the server at Finish | The dates mean "when this step really happened", so they come from the server clock (business time zone), never from a form: nobody can backdate one, and the order import ≤ production ≤ packing follows from the step order and reopen rules, with no extra validation. The batch code keeps the creation day and never changes. |
| Plan gate before step 3 | Packing follows a decision (how many 4-piece and 2-piece packs), so step 3 is locked until a planner confirms it, and the API enforces it (`PRODUCTION_PLAN_REQUIRED`), not just the UI. The plan lives in its own table with its own permissions, so who plans is independent of who records; it shares the batch `version`, so plan and step writes can't overwrite each other. Reopening step 1 or 2 resets it to pending (the counts may change); a mismatch between plan and actual needs a comment rather than being forbidden. |
| Notifications stored first, Telegram after commit | An alert must exist exactly when the step was finished, and Telegram must never slow down or break a Finish. Rows are written in the Finish transaction (the bell always works); sending happens afterwards in a background task that records its outcome per row, so failures are visible and can be resent. No queue or worker process is needed at this size. |
| Superadmin links Telegram with a one-time token | The superadmin has no Telegram username to be matched by, and must stay invisible. A short-lived, single-use, hashed deep-link token binds exactly the account that opens it, without the superadmin typing an id, and the bot's replies never mention a role. |
| Role limits in a table with a row lock instead of a unique index | A partial unique index can only express "at most one". Limits the superadmin can change need a number stored as data; locking that row while counting keeps the check race-safe (one request takes the last slot) without a table lock. Lowering a limit never deactivates anyone: it only blocks new users, which is safer than guessing whom to remove. |
| Cancelling batches is GM-only | Cancelling removes a batch from the figures: a management decision, like deactivating people. Outside the feature levels, so a supervisor at Full access can fix steps but not cancel. |
| Feature levels for managers, detailed permissions for the superadmin | Managers think in "who can use Suppliers, and how much", not in permission codes. Levels are exact code sets over the same `user_permissions` table, so nothing else changes and the superadmin can still fine-tune (shown as `custom`). |
| Superadmin redacted for all other viewers | The superadmin is an operator account, not part of the business. Hiding it at the serialization edge (one `UserRef` schema, one lookup helper, fail-closed) covers new endpoints by default, and a route-walking test guards against regressions. |
| Supervisors never deactivate users or hold `permissions.grant` | Keeps people decisions with general managers. Enforced by `assignable_to`, so older grants lose their effect without a data migration. |
| Supervisors manage staff access with their own permission, capped by what they were given | Supervisors know what their staff need, so by default they set staff levels, but never above their own: a GM or the superadmin stays the source of all access. A new permission (`users.manage_access`) instead of making `permissions.grant` assignable again: old supervisors still have stale `permissions.grant` rows that would silently become effective, and `permissions.grant` would also bring the GM's uncapped meaning. The cap is computed from the supervisor's effective permissions at request time, with no cascade, like revoking. |
| Viewing, adding and editing staff are separate levels | Seeing staff (to set their access) is everyday work; adding people and changing their details are decisions the GM makes per supervisor. Staff management gets a *Record* level (view + create) between View only and Full access (+ update), the same pattern as Production, so each step is one click on the Access tab instead of detailed permissions. |
| Backfill role defaults only for newly inserted permissions | New features reach existing managers on deploy with no manual grants, and it runs exactly once per permission, so a later deliberate revoke is never undone by a restart. |
| `grantable_by` on the permission, not a new role rule | Keeps the hierarchy (who manages whom) unchanged, and restricts only the permissions that need it, per target role. The superadmin is exempt, matching "implicit-all". Unused today; kept for later. |
| Separate `suppliers` and `customers` tables, one generic implementation | Each list gets its own ids, indexes and future columns, while the code and tests are written once. |
| Phones stored normalized, displayed formatted | Search and the uniqueness index work on one canonical form, whatever separators people type. |
| Production as a batch with one row per step | The three steps have different fields, owners and lifecycles (draft / finished, reopen). One table per step keeps each typed and constrained, a missing row means "not started", and a batch loads with all steps at once. |
| Server-side drafts with a batch `version` | Autosave needs the half-filled form on the server (the Mini App may be closed any time, work continues on another device). Optimistic versioning (`409 PRODUCTION_CONFLICT` with the current batch) is simpler than locking a batch to one user and still prevents silent overwrites; the row lock (`FOR UPDATE`) serializes concurrent writes. |
| Piece counts computed by the server | `wings_count` / `thighs_count` follow from the chicken count; accepting them from clients would let the balance check be bypassed. |
| Inventory as a ledger with balances | An append-only movement per change (with the balance after it) gives a full history and lets reopen / cancel undo exactly what a step did, as new reversing movements instead of edits. A balance row per item makes reads cheap and is the lock point: `apply_movements` locks the rows in `item_code` order (the batch row is always locked first), checks nothing goes below zero and writes in the caller's transaction, so a refused change rolls back the whole action. |
| Old batches not tracked | Batches finished before inventory existed never added stock, so reversing them on reopen or cancel would remove stock that isn't there (or go negative). `inventory_tracked = false` for them (migration) keeps inventory starting at zero and consistent. |
| Estimated waste kg | Rejected wings and thighs are counted, not weighed. Their kg is estimated as rejected count × the batch's average piece weight (step 2 kg ÷ count), marked `kg_estimated` so the UI shows "≈". |
| Production items are read-only in inventory | Every item today is made and used by production, and its per-batch breakdown and history only add up if production is the only thing that changes it. Hand-set values (opening stock, recounts) would mix in quantities that belong to no batch. So `set` refuses production items for everyone, the superadmin included (`INVENTORY_ITEM_PRODUCTION_ONLY`), migration `0011` removed the adjustments made before, and `inventory.adjust` is inactive until `manual` items exist (`ItemDef.origin`). |
| Features a grantor doesn't hold are invisible to them | Some access (inventory history) is the superadmin's to hand out, then passed on by those who have it. A general manager without it shouldn't learn it exists: a 403 or a disabled row would reveal it. So for them the feature is absent from the matrix, PUT answers `FEATURE_NOT_FOUND`, and its audit entries are hidden. The rule is a flag on the feature (`grantor_must_hold`), so the next such feature needs no new code. |
| Per-batch breakdown computed from the ledger | "Where did this stock come from" is the sum of each batch's movements for the item (every source), so it needs no extra table and always equals the balance, because every movement — including orders' — is attributed to a batch. |
| Stock leaves at Delivering | The packs are physically gone when the driver leaves, not when the order is typed in: orders are often entered ahead, edited or cancelled. Taking stock at Delivering keeps Created orders free to change (they only warn), makes Cancel a pure status change, and puts the one hard stock check (`INVENTORY_INSUFFICIENT`) where it matters. |
| FIFO by batch keeps the breakdown exact | Each order movement is split across batches, oldest first (one movement per item and batch), and returns go back to the batches they came from, newest first. The per-batch breakdown stays equal to the balance with no extra table, older packs go out first, and every pack can be traced to its batch and order. |
| Production reversal blocked once stock is used | Reopening or cancelling a batch takes back what it made; if its packs are already with a customer, undoing them would make the batch's contribution negative and the history false. So the reversal needs the batch's own remaining stock (`PRODUCTION_STOCK_ALREADY_USED`, naming the orders), checked after locking the balances so a concurrent Delivering can't slip in between. A return to stock frees the batch again. |
| Order lines as rows for future prices | Boxes and their lines are tables (`order_boxes`, `order_box_items`), not JSON, so the database checks them (units, one line per item per box) and prices can later be columns on the line (`unit_price`, `amount`) without restructuring. The box colour is a code for the same reason. |
| Order alerts to whoever reviews returns | The people who must act on a return are the ones told about deliveries: one permission (`orders.review_returns`) decides both, like the plan feature for production alerts. `notify` takes the permission, so the mechanism is shared. |
| Server-side PDF instead of browser print (Telegram WebView) | The Mini App runs in Telegram's WebView, where `window.print()` and downloads are unreliable or missing, and phone browsers print web pages at A4 with their own headers. A PDF rendered by the API looks the same everywhere, can be sent to the person's Telegram chat (from where it prints or forwards), and gives one place to number originals and copies. WeasyPrint keeps the layout in HTML/CSS (the team's language) and shapes Khmer through HarfBuzz with a bundled font. |
| Receipt layout black-and-white | Thermal receipt printers print black dots only: colours vanish and greys dither into noise. Nothing carries meaning through colour (box colour = filled / outlined square + its name), rules are solid black, the page is 80 mm wide and as tall as its content so no paper is wasted. |
| One template for delivery note and future invoice | The invoice is the delivery note plus prices. One template with price columns behind `show_prices`, and one switch (`kind_for`) for the title, means prices are a data change (line columns) plus flipping that switch, not a second document to keep in sync. |
| Print count outside the order version | Printing doesn't change the order; bumping `version` would make anyone editing it hit `ORDER_CONFLICT` because a driver printed. The count is incremented atomically on its own column, which also serializes concurrent prints so exactly one is the original. |
| By-product kg balance enforced by the UI only (for now) | Weights are measured on a scale and may legitimately not add up exactly; the business may relax the rule. Keeping it out of the API means that change is UI-only; a test documents that the API accepts it. |
| Batch code from a per-day counter row | Readable, gap-free per day and race-safe (`ON CONFLICT … RETURNING`), without a sequence per day. |
| Always `200` once the secret is valid | Telegram retries non-2xx responses, so a failing handler would otherwise replay the same update in a loop. Failures are logged instead. |
