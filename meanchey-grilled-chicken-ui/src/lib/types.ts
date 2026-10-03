export type Role = 'superadmin' | 'general_manager' | 'supervisor' | 'staff'
export type Language = 'km' | 'en'

/** Staff job title: free text, a label only (never used for access). Same limit as the API. */
export const POSITION_MAX_LENGTH = 50
export const LANGUAGES: Language[] = ['km', 'en']

/**
 * A reference to another user. `is_system` marks actions by the system (and accounts the viewer
 * can't see): render it as "System", without a link. Then `id` is null.
 */
export interface UserRef {
  id: string | null
  full_name: string
  role: Role | null
  telegram_username: string | null
  is_system: boolean
}

export interface User {
  id: string
  role: Role
  position: string | null
  full_name: string
  phone: string | null
  telegram_username: string | null
  telegram_linked: boolean
  language: Language
  is_active: boolean
  must_change_password: boolean
  created_by: UserRef | null
  created_at: string
  updated_at: string
  deleted_at: string | null
  locked_until: string | null
}

export interface Me {
  user: User
  permissions: string[]
  manageable_roles: Role[]
  can_self_reset_password: boolean
  /** May set feature access levels (the Access tab on user details). */
  /** permissions.grant (GM, superadmin) or users.manage_access (supervisor, staff only). */
  can_manage_features: boolean
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  must_change_password: boolean
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Localized {
  name_en: string
  name_km: string
}

export interface UserPermission extends Localized {
  code: string
  module: string
  description_en: string
  description_km: string
  assignable_to: Role[]
  granted: boolean
  granted_by: string | null
  granted_at: string | null
  can_edit: boolean
  /** Error code of the first rule that blocks the viewer from editing this item, or null. */
  reason: string | null
}

export interface UserPermissionModule extends Localized {
  module: string
  permissions: UserPermission[]
}

export interface UserPermissions {
  user_id: string
  modules: UserPermissionModule[]
}

export type PartnerEntityType = 'supplier' | 'customer'
export type AuditEntityType = PartnerEntityType | 'production_batch'

/** Non-user record an audit entry is about. `name` is its current name (or the logged one). */
export interface AuditEntityRef {
  type: AuditEntityType | string
  id: string
  name: string | null
}

export interface AuditLog {
  id: number
  action: string
  actor: UserRef | null
  target: UserRef | null
  entity: AuditEntityRef | null
  details: Record<string, unknown>
  created_at: string
}

/** A supplier or customer (same shape; see /suppliers and /customers). */
export interface Partner {
  id: string
  name: string
  location: string | null
  /** Normalized: digits with an optional leading +. */
  phone: string | null
  /** Readable form, e.g. "012 345 678". */
  phone_display: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  deleted_at: string | null
  created_by: UserRef | null
  updated_by: UserRef | null
}

export interface PartnerStats {
  total_active: number
  /** Added during the current calendar month (business time zone), any status. */
  new_this_month: number
  inactive: number
}

/** Same limits as the API. */
export const PARTNER_NAME_MAX_LENGTH = 150
export const PARTNER_LOCATION_MAX_LENGTH = 255
export const PHONE_MIN_DIGITS = 8
export const PHONE_MAX_DIGITS = 15

/** Feature access levels (Access tab). `custom` = the permissions match no level exactly. */
export type FeatureLevel = 'off' | 'view' | 'record' | 'full'
export type FeatureMenu = 'workstation' | 'settings'

export interface Feature extends Localized {
  code: string
  menu: FeatureMenu
  description_en: string
  description_km: string
  /** Settable levels, in order (always starts with `off`). `allowed` is false when the level is
   *  above the viewer's own access (a supervisor setting staff access). */
  levels: { level: FeatureLevel; allowed: boolean }[]
  current_level: FeatureLevel | 'custom'
  can_edit: boolean
}

export interface UserFeatures {
  user_id: string
  menus: { menu: FeatureMenu; features: Feature[] }[]
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> }
}

// --- Production -------------------------------------------------------------------------------

export type BatchStatus = 'in_progress' | 'completed' | 'cancelled'
export type StepStatus = 'draft' | 'finished'
/** API path segment of each step: /production/{id}/{slug}. */
export type StepSlug = 'raw-material' | 'produced' | 'standardize'
export type StepNumber = 1 | 2 | 3

export interface SupplierBrief {
  id: string
  name: string
  phone_display: string | null
  is_active: boolean
}

export interface SupplierOption {
  id: string
  name: string
  phone_display: string | null
}

interface StepBase {
  status: StepStatus
  /** Steps that go back to draft if this one is edited (itself + later finished steps); [] if not finished. */
  reopens_steps: StepNumber[]
  finished_by: UserRef | null
  finished_at: string | null
  updated_by: UserRef | null
  updated_at: string
}

/** Weights are fixed-precision strings: kg "12.500", grams "350.0". */
export interface RawMaterialStep extends StepBase {
  supplier: SupplierBrief | null
  material_kind: string
  weight_kg: string | null
  quantity: number | null
  /** ថ្ងៃនាំចូល: recorded by the server when step 1 is finished; null while a draft. */
  import_date: string | null
}

export interface ProducedStep extends StepBase {
  wings_kg: string | null
  thighs_kg: string | null
  /** Computed by the server: quantity × 2. */
  wings_count: number
  thighs_count: number
  marinade_g: string | null
  /** ថ្ងៃផលិត: recorded when step 2 is finished; null while a draft. */
  production_date: string | null
}

export interface StandardizeStep extends StepBase {
  big_packages: number | null
  small_packages: number | null
  rejected_wings: number | null
  rejected_thighs: number | null
  comment: string | null
  /** ថ្ងៃវេចខ្ចប់: recorded when step 3 is finished; null while a draft. */
  packaging_date: string | null
  /** Both pack counts equal the plan's; null until both actual counts (and a plan) exist. */
  plan_matches: boolean | null
}

export type PlanStatus = 'pending' | 'confirmed'

/** The packaging plan between steps 2 and 3: expected 4-piece (big) and 2-piece (small) packs. */
export interface ProductionPlan {
  status: PlanStatus
  expected_big: number | null
  expected_small: number | null
  note: string | null
  confirmed_by: UserRef | null
  confirmed_at: string | null
  updated_by: UserRef | null
  updated_at: string
}

export interface BatchByproduct {
  item_code: string
  produced_kg: string | null
  carry_kg: string | null
  rejected_kg: string | null
}

export interface ByproductCatalogItem extends Localized {
  code: string
  unit: string
  order: number
}

export interface MaterialKind extends Localized {
  code: string
  wings_per_unit: number
  thighs_per_unit: number
}

export interface ProductionBatch {
  id: string
  /** PR-YYYYMMDD-NNN from the creation day; never changes. */
  code: string
  status: BatchStatus
  current_step: StepNumber
  version: number
  cancel_reason: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
  cancelled_at: string | null
  created_by: UserRef | null
  updated_by: UserRef | null
  cancelled_by: UserRef | null
  raw_material: RawMaterialStep
  /** null until step 1 is finished for the first time (likewise `standardize` for step 2). */
  produced: ProducedStep | null
  standardize: StandardizeStep | null
  /** Created when step 2 is finished; null before that and for batches finished before plans existed. */
  plan: ProductionPlan | null
  /** No plan because the batch was finished before plans existed. */
  plan_legacy: boolean
  byproducts: BatchByproduct[]
  computed: { wings_count: number; thighs_count: number; yield_percent: string | null }
  catalog: { byproducts: ByproductCatalogItem[]; material_kinds: MaterialKind[] }
  /** Only with inventory.history (otherwise absent). False for batches created before inventory
   *  existed: they never move stock. */
  inventory_tracked?: boolean
  /** Only with inventory.history: net stock changes of the finished steps (reversed left out). */
  stock_changes?: StockChange[]
}

export interface ProductionBatchListItem {
  id: string
  code: string
  /** Step dates (YYYY-MM-DD), null until that step is finished. */
  import_date: string | null
  production_date: string | null
  packaging_date: string | null
  created_at: string
  status: BatchStatus
  current_step: StepNumber
  steps: ('pending' | StepStatus)[]
  supplier: SupplierBrief | null
  material_kind: string
  quantity: number | null
  created_by: UserRef | null
  updated_at: string
}

export interface ProductionStats {
  in_progress: number
  completed_today: number
  chickens_this_month: number
  rejected_pieces_this_month: number
}

export interface PlanListItem {
  batch_id: string
  code: string
  batch_status: BatchStatus
  supplier: SupplierBrief | null
  production_date: string | null
  quantity: number | null
  wings_count: number
  thighs_count: number
  status: PlanStatus
  expected_big: number | null
  expected_small: number | null
  updated_at: string
}

export interface PlanPage extends Page<PlanListItem> {
  /** Plans waiting to be set, whatever the filter. */
  pending_count: number
}

export interface PlanDetail {
  batch_id: string
  code: string
  batch_status: BatchStatus
  current_step: StepNumber
  /** The batch version: every plan write sends it. */
  version: number
  supplier: SupplierBrief | null
  quantity: number | null
  produced: {
    status: StepStatus
    production_date: string | null
    wings_kg: string | null
    thighs_kg: string | null
    wings_count: number
    thighs_count: number
    marinade_g: string | null
    byproducts: (Localized & { item_code: string; produced_kg: string | null })[]
  } | null
  standardize: {
    status: StepStatus
    big_packages: number | null
    small_packages: number | null
    comment: string | null
    packaging_date: string | null
  } | null
  plan: ProductionPlan | null
  plan_legacy: boolean
  /** Step 2 finished, step 3 not finished, not cancelled (still needs production_plan.manage). */
  editable: boolean
}

// --- Notifications ----------------------------------------------------------------------------

export type NotificationType = 'production.processing_finished' | 'production.completed'

export interface AppNotification {
  id: string
  type: NotificationType
  entity_type: string
  entity_id: string
  /** processing_finished: {code, quantity, wings, thighs, repeat};
   * completed: {code, matches, planned_big, planned_small, actual_big, actual_small, comment, repeat}. */
  payload: Record<string, unknown>
  actor: UserRef | null
  created_at: string
  read_at: string | null
  telegram_status: 'pending' | 'sent' | 'failed' | 'not_linked' | 'bot_off'
}

export interface NotificationPage extends Page<AppNotification> {
  unread_count: number
}

export interface TelegramLink {
  url: string
  expires_at: string
}

/** Same limits as the API. */
export const PRODUCTION_COMMENT_MAX_LENGTH = 1000
export const PLAN_NOTE_MAX_LENGTH = 500
export const CANCEL_REASON_MAX_LENGTH = 500

// --- Role limits ------------------------------------------------------------------------------

/** Roles with a configurable number of active users (the superadmin is always exactly one). */
export type LimitedRole = 'general_manager' | 'supervisor' | 'staff'

export interface RoleLimit {
  role: LimitedRole
  /** null = unlimited (never for the general manager). */
  max_active: number | null
  active: number
  /** More active users than the limit (it was lowered): nobody new until some leave. */
  over_limit: boolean
  updated_by: UserRef | null
  updated_at: string | null
}

export interface RoleCapacity {
  role: LimitedRole
  active: number
  /** null = unlimited */
  limit: number | null
  full: boolean
}

/** Same range as the API. */
export const ROLE_LIMIT_MAX = 999

// --- Inventory --------------------------------------------------------------------------------

export type InventorySection = 'stock' | 'wasted'
export type InventoryGroup = 'raw' | 'processed' | 'packed' | 'wasted'
export type MovementSource = 'production' | 'adjustment'

/** An item and its balance. `count` / `kg` are null for a unit the item doesn't track. */
export interface InventoryItem extends Localized {
  code: string
  section: InventorySection
  group: InventoryGroup
  tracks_count: boolean
  tracks_kg: boolean
  /** Its kg is estimated from the batch's average piece weight (wasted pieces). */
  kg_estimated: boolean
  /** `production`: changes only through production (every item today). */
  origin: 'production' | 'manual'
  count: number | null
  kg: string | null
  /** Time of the latest movement; null if it never changed. */
  updated_at: string | null
}

/** What one batch currently contributes to an item's balance (net of its reversals). */
export interface ItemSource {
  batch_id: string
  code: string
  count: number | null
  kg: string | null
  kg_estimated: boolean
  /** The latest step of this batch that still contributes. */
  last_step: StepNumber
}

/** `GET /inventory/items/{code}`: the item and, per batch, where its current stock came from. */
export interface InventoryItemDetail extends InventoryItem {
  /** Oldest batch first; adds up to the balance. */
  sources: ItemSource[]
}

export interface InventoryOverview {
  sections: { section: InventorySection; items: InventoryItem[] }[]
}

export interface InventoryMovement extends Localized {
  id: number
  item_code: string
  section: InventorySection | null
  count_delta: number | null
  kg_delta: string | null
  kg_estimated: boolean
  source: MovementSource
  batch: { id: string; code: string } | null
  step: StepNumber | null
  /** Set on a reversal: the movement it undoes (`reason` is then "reopen" or "cancel"). */
  reversal_of: number | null
  reason: string | null
  balance_count_after: number | null
  balance_kg_after: string | null
  created_by: UserRef | null
  created_at: string
}

export interface StockChange extends Localized {
  step: StepNumber
  item_code: string
  section: InventorySection | null
  count_delta: number | null
  kg_delta: string | null
  kg_estimated: boolean
}

