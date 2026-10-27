import type { QuantityUnit } from './quantity'

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
  /** Attendance workplace (staff and supervisors). */
  workplace?: { id: string; name: string } | null
  /** First tracked day (staff and supervisors; null for the others). */
  attendance_start_date?: string | null
  /** Staff are always tracked; a supervisor can be switched off. */
  attendance_tracked?: boolean
  /** Since when a supervisor is not tracked (null while tracked). */
  attendance_untracked_since?: string | null
  /** `GET /users/{id}` with attendance.view or attendance.scheduling: their schedule today. */
  attendance_schedule_summary?: ScheduleSummary | null
}

export interface Me {
  user: User
  permissions: string[]
  manageable_roles: Role[]
  can_self_reset_password: boolean
  /** May set feature access levels (the Access tab on user details). */
  /** permissions.grant (GM, superadmin) or users.manage_access (supervisor, staff only). */
  can_manage_features: boolean
  /** Holds an alert permission or is tracked for attendance: alerts / reminders go to Telegram. */
  telegram_alerts: boolean
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
export type AuditEntityType = PartnerEntityType | 'production_batch' | 'preparation'

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
export type FeatureMenu = 'workstation' | 'attendance' | 'settings'

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
  /** Satay sachets used: one per pack by default (4-piece per big pack, 2-piece per small). */
  sachets_4_used: number | null
  sachets_2_used: number | null
  /** False: the count follows its pack count (auto); true: typed by hand. */
  sachets_4_manual: boolean
  sachets_2_manual: boolean
  comment: string | null
  /** ថ្ងៃវេចខ្ចប់: recorded when step 3 is finished; null while a draft. */
  packaging_date: string | null
  /** Both pack counts equal the plan's; null until both actual counts (and a plan) exist. */
  plan_matches: boolean | null
  /** Satay sachets in stock by size (Finish takes the counts out of them). Only with
   * production.create while step 3 of a tracked, active batch is a draft. */
  sachet_stock?: SachetCounts | null
}

/** A count per satay sachet size: "4" (4-piece packs) and "2" (2-piece packs). */
export interface SachetCounts {
  '4': number
  '2': number
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
  /** Step 2 form: the Marinade sauce in stock (Finish takes marinade_g out of it). Only with
   * production.create while step 2 of a tracked batch is a draft. */
  marinade_stock?: { unit: QuantityUnit; count: number | null; kg: string | null; g: string | null } | null
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
  /** Satay sachets the plan needs (one per pack) vs the stock; information only. Null until both
   * expected counts are set, for batches that don't move stock, and once step 3 is finished. */
  sachets: { needed: SachetCounts; in_stock: SachetCounts; short: SachetCounts } | null
  /** Step 2 finished, step 3 not finished, not cancelled (still needs production_plan.manage). */
  editable: boolean
}

// --- Notifications ----------------------------------------------------------------------------

export type NotificationType =
  | 'production.processing_finished'
  | 'production.completed'
  | 'order.delivering'
  | 'order.delivered'
  | 'order.return_pending'
  | 'order.returns_reviewed'
  | 'preparation.finished'
  | 'attendance.request_submitted'
  | 'attendance.request_approved'
  | 'attendance.request_rejected'
  | 'attendance.request_reminder'
  | 'attendance.schedule_changed'
  | 'attendance.holiday_work'
  | 'attendance.holiday_off'
  | 'inventory.cleared'

export interface AppNotification {
  id: string
  type: NotificationType
  entity_type: string
  entity_id: string
  /** processing_finished: {code, quantity, wings, thighs, repeat};
   * completed: {code, matches, planned_big, planned_small, actual_big, actual_small, comment, repeat};
   * order.*: {code, customer (null for a direct order), customer_type, customer_phone (readable),
   * white, black (delivering), returned + reason (return_pending),
   * outcome + to_stock + to_wasted (returns_reviewed)}; items are OrderAlertItem[];
   * preparation.finished: {code, type, sachets_2, sachets_4, materials: PreparationAlertMaterial[],
   * repeat};
   * attendance.request_*: {year, month, missing_minutes, salary_cut_minutes, unpaid_work_minutes,
   * name (submitted), with_changes + comment (approved), reason (rejected), balance_minutes +
   * deadline_day + deadline_month (reminder)};
   * attendance.schedule_changed: {effective_from, weekdays, shifts: [{code, start_time, end_time}],
   * custom}; attendance.holiday_work / _off: {holiday, holiday_km, date, shifts (work)};
   * inventory.cleared: {code, items: ClearAlertItem[], reason, impacts: {order?: n, …}}. */
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

export type InventorySection = 'stock' | 'prepared' | 'wasted'
export type InventoryGroup = 'raw' | 'processed' | 'packed' | 'prepared' | 'wasted'
/** What a preparation may do with a material (not editable in the UI yet). */
export type PrepRole = 'none' | 'packaging' | 'satay_sauce' | 'zip_bag_2' | 'zip_bag_4'
/** order: stock out at Delivering; order_return: returned items at the review. */
export type MovementSource =
  | 'production'
  | 'adjustment'
  | 'order'
  | 'order_return'
  | 'material_add'
  | 'material_remove'
  | 'material_unit_change'
  | 'preparation'
  | 'clear'

/** Set on materials (origin manual): what the Raw cards and sheets need. */
export interface ItemMaterial {
  id: string
  unit: QuantityUnit
  /** e.g. "marinade": used by production; can't be archived or switched to count. */
  system_code: string | null
  archived: boolean
  /** A picture bundled with the UI (`src/assets/inventory/materials/<key>.svg`), or null. */
  icon_key: string | null
  /** The uploaded icon (API path, versioned; load with the API client), shown first; or null. */
  icon_url: string | null
  /** packaging: has a prepared twin; satay_sauce / zip_bag_*: satay sachet inputs; none. */
  prep_role?: PrepRole
}

/** An item and its balance. `count` / `kg` are null for a unit the item doesn't track. */
export interface InventoryItem extends Localized {
  code: string
  section: InventorySection
  group: InventoryGroup
  tracks_count: boolean
  tracks_kg: boolean
  /** Materials measured in grams. */
  tracks_g: boolean
  /** Materials measured in square metres. */
  tracks_m2: boolean
  /** Its kg is estimated from the batch's average piece weight (wasted pieces). */
  kg_estimated: boolean
  /** `production`: changes only through production and orders; `manual`: a material;
   * `preparation`: made by preparations (satay sachets, prepared twins of materials). */
  origin: 'production' | 'manual' | 'preparation'
  count: number | null
  kg: string | null
  g: string | null
  m2: string | null
  /** Time of the latest movement; null if it never changed. */
  updated_at: string | null
  material: ItemMaterial | null
}

/** GET /inventory/materials (and every material write). The balance is in `unit`. */
export interface Material {
  id: string
  item_code: string
  name_km: string
  name_en: string
  unit: QuantityUnit
  system_code: string | null
  icon_key: string | null
  icon_url: string | null
  prep_role: PrepRole
  count: number | null
  kg: string | null
  g: string | null
  m2: string | null
  /** Any movement yet: switching to / from count or m² is then locked. */
  has_movements: boolean
  archived_at: string | null
  archived_by: UserRef | null
  created_by: UserRef | null
  created_at: string
  updated_by: UserRef | null
  updated_at: string
}

export const MATERIAL_NAME_MAX_LENGTH = 100
export const MATERIAL_REASON_MAX_LENGTH = 500

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
  /** Prepared items: the same per preparation (oldest first). */
  preparation_sources?: ItemPreparationSource[]
}

/** What one preparation currently adds to a prepared item. */
export interface ItemPreparationSource {
  preparation_id: string
  code: string
  prepared_date: string | null
  count: number | null
  kg: string | null
  g: string | null
  m2: string | null
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
  g_delta: string | null
  m2_delta: string | null
  kg_estimated: boolean
  source: MovementSource
  /** Production: the batch. Orders: the batch the quantity is attributed to (oldest first). */
  batch: { id: string; code: string } | null
  /** Order and return movements: the order. */
  order?: { id: string; code: string } | null
  /** Preparation movements: the preparation. */
  preparation?: { id: string; code: string } | null
  /** Clear movements: the clear (CL-…). */
  clear?: { id: string; code: string } | null
  step: StepNumber | null
  /** Set on a reversal: the movement it undoes (`reason` is then "reopen" or "cancel"). */
  reversal_of: number | null
  reason: string | null
  balance_count_after: number | null
  balance_kg_after: string | null
  balance_g_after: string | null
  balance_m2_after: string | null
  created_by: UserRef | null
  created_at: string
}

// --- Clear stock --------------------------------------------------------------------------------

/** One item of the inventory.cleared alert. */
export interface ClearAlertItem {
  name_en: string
  name_km: string
  quantity: string
  unit: QuantityUnit
}

export const CLEAR_REASON_MAX_LENGTH = 500

export type ClearImpactType = 'order' | 'production' | 'plan' | 'preparation' | 'reopen'
export type ClearImpactMessage =
  | 'order_short'
  | 'production_step2_short'
  | 'production_step3_short'
  | 'plan_sachets_short'
  | 'preparation_short'
  | 'reopen_batch_blocked'
  | 'reopen_preparation_blocked'

/** Something a clear leaves short (it doesn't block the clear, but must be acknowledged). */
export interface ClearImpact extends Localized {
  type: ClearImpactType
  /** The order, batch or preparation code and id (for the link). */
  code: string
  id: string
  step: StepNumber | null
  item_code: string
  unit: QuantityUnit
  needed: string
  available_after: string
  message_key: ClearImpactMessage
}

export interface ClearItemRef extends Localized {
  item_code: string
  section: InventorySection | null
}

export interface ClearPreviewLine extends Localized {
  item_code: string
  section: InventorySection
  group: InventoryGroup
  unit: QuantityUnit
  current: string
  clear: string
  after: string
  /** Counted items that also track kg: the kg taken (≈ when estimated). */
  kg: string | null
  kg_estimated: boolean
  /** The wasted item it moves to; null: removed. */
  destination: ClearItemRef | null
}

export interface ClearPreview {
  lines: ClearPreviewLine[]
  impacts: ClearImpact[]
}

export interface InventoryClearLine extends Localized {
  item_code: string
  section: InventorySection | null
  unit: QuantityUnit
  quantity: string
  kg: string | null
  kg_estimated: boolean
  moved_to: ClearItemRef | null
}

export interface InventoryClear {
  id: string
  code: string
  reason: string
  lines: InventoryClearLine[]
  /** The impacts acknowledged when it was made. */
  impacts: ClearImpact[]
  created_by: UserRef | null
  created_at: string
}

export interface StockChange extends Localized {
  step: StepNumber
  item_code: string
  section: InventorySection | null
  count_delta: number | null
  kg_delta: string | null
  g_delta: string | null
  m2_delta: string | null
  kg_estimated: boolean
}


// --- Orders -----------------------------------------------------------------------------------

export type OrderStatus =
  | 'created'
  | 'delivering'
  | 'return_pending'
  | 'success'
  | 'partly_returned'
  | 'fully_returned'
  | 'cancelled'
/** The container of a box (named "color" since the first two were white / black boxes). */
export type BoxColor = 'white' | 'black' | 'plastic_bag' | 'delivery_bag'
/** In the API's order (summaries, list counts, the Add box choice). */
export const BOX_COLORS: BoxColor[] = ['white', 'black', 'plastic_bag', 'delivery_bag']
/** Whether a container of this type must come back, unless the box says otherwise (the API's
 * BOX_RETURNABLE). */
export const BOX_RETURNABLE: Record<BoxColor, boolean> = {
  white: true,
  black: true,
  plastic_bag: false,
  delivery_bag: false,
}
/** A returnable box's container: pending until Delivered, then returned / not returned. */
export type ContainerStatus = 'pending' | 'returned' | 'not_returned'
/** Packs are counted (whole numbers), packed by-products weighed (kg, 3 decimals). */
export type OrderUnit = 'count' | 'kg'

/** Same limits as the API. */
export const ORDER_NOTE_MAX_LENGTH = 1000
export const ORDER_REASON_MAX_LENGTH = 500
export const CONTAINER_REASON_MAX_LENGTH = 300

export interface OrderItemRef extends Localized {
  item_code: string
  unit: OrderUnit
}

/** A quantity of one item: `count` for packs, `kg` for by-products (the other is null). */
export interface OrderQuantity extends OrderItemRef {
  count: number | null
  kg: string | null
}

export interface OrderBox {
  id: string
  color: BoxColor
  position: number
  /** The container must come back. */
  returnable: boolean
  /** null when not returnable or the order was cancelled. */
  container_status: ContainerStatus | null
  container_reason: string | null
  container_recorded_by: UserRef | null
  container_recorded_at: string | null
  container_returned_later_by: UserRef | null
  container_returned_later_at: string | null
  lines: OrderQuantity[]
}

export interface ContainersSummary {
  total_returnable: number
  returned: number
  not_returned: number
  pending: number
}

export interface OrderSummary {
  /** White box, black box, plastic bag, delivery bag (those without boxes left out). */
  colors: { color: BoxColor; boxes: number; items: OrderQuantity[] }[]
  total: { boxes: number; items: OrderQuantity[] }
}

export interface OrderReturnItem extends OrderItemRef {
  delivered_count: number | null
  delivered_kg: string | null
  returned_count: number | null
  returned_kg: string | null
  /** null until reviewed */
  to_stock_count: number | null
  to_stock_kg: string | null
  to_wasted_count: number | null
  to_wasted_kg: string | null
  reviewed_by: UserRef | null
  reviewed_at: string | null
}

export interface StockWarning extends OrderItemRef {
  available_count: number | null
  available_kg: string | null
  needed_count: number | null
  needed_kg: string | null
}

/** saved: a customer from Customers; direct: no saved customer, a phone (+ location) for this order. */
export type OrderCustomerType = 'saved' | 'direct'

/** The order's customer, from its snapshot (frozen from Delivering on). A direct order has no id
 * and no name (shown as "Direct order") but always a phone. */
export interface CustomerBrief {
  type: OrderCustomerType
  id: string | null
  name: string | null
  /** Normalized: digits with an optional leading +. */
  phone: string | null
  phone_display: string | null
  location: string | null
  /** The saved customer's current status; null for direct orders. */
  is_active: boolean | null
}

export interface Order {
  id: string
  code: string
  status: OrderStatus
  customer: CustomerBrief
  /** A calendar day ("2026-10-03"). */
  delivery_date: string
  driver: UserRef | null
  note: string | null
  return_reason: string | null
  cancel_reason: string | null
  version: number
  /** Delivery notes generated so far; the next one prints as a COPY when ≥ 1. */
  print_count: number
  created_by: UserRef | null
  created_at: string
  updated_by: UserRef | null
  updated_at: string
  delivering_by: UserRef | null
  delivering_at: string | null
  delivered_by: UserRef | null
  delivered_at: string | null
  returns_reviewed_by: UserRef | null
  returns_reviewed_at: string | null
  cancelled_by: UserRef | null
  cancelled_at: string | null
  boxes: OrderBox[]
  summary: OrderSummary
  /** null for cancelled orders (containers don't apply). */
  containers: ContainersSummary | null
  returns: OrderReturnItem[]
  /** Only while Created: items whose stock is below the order's totals right now. */
  stock_warnings: StockWarning[]
}

export interface OrderListItem {
  id: string
  code: string
  status: OrderStatus
  customer: CustomerBrief
  delivery_date: string
  driver: UserRef | null
  white_boxes: number
  black_boxes: number
  plastic_bag_boxes: number
  delivery_bag_boxes: number
  /** Boxes recorded as not returned (and not returned later). */
  containers_outstanding: number
  created_at: string
  updated_at: string
}

export interface OrderStats {
  created: number
  delivering: number
  return_pending: number
  delivered_this_month: number
}

export interface CustomerOption {
  id: string
  name: string
  phone_display: string | null
  location: string | null
}

export interface DriverOption {
  id: string
  full_name: string
  role: 'supervisor' | 'staff'
}

/** `GET /orders/available-stock`: current stock of the orderable items. */
export type AvailableItem = OrderQuantity

/** An item in an order alert's payload (names kept with it). */
export interface OrderAlertItem extends Localized {
  item_code: string
  count: number | null
  kg: string | null
}

/** POST /orders/{id}/document/send-telegram */
export interface DocumentSent {
  /** 1 = the original, 2+ = a copy. */
  copy_number: number
}

/** GET /orders/delivery-note/supplier: the supplier block of the Excel delivery note. */
export interface BusinessSupplier {
  name_km: string
  name_en: string
  address_km: string | null
  address_en: string | null
  phone: string | null
  phone_display: string | null
}

/** GET/PUT /settings/business: what delivery notes print at the top and bottom. */
export interface BusinessInfo {
  name_km: string
  name_en: string
  address_km: string | null
  address_en: string | null
  phone: string | null
  phone_display: string | null
  footer_note_km: string | null
  footer_note_en: string | null
  has_logo: boolean
  logo_mime: string | null
  updated_by: UserRef | null
  updated_at: string
}

export const BUSINESS_NAME_MAX_LENGTH = 200
export const BUSINESS_ADDRESS_MAX_LENGTH = 500
export const BUSINESS_FOOTER_MAX_LENGTH = 300
export const LOGO_MAX_BYTES = 500 * 1024

// --- Preparations -----------------------------------------------------------------------------

export type PreparationType = 'satay_sachet' | 'packaging_material'
export type PreparationStatus = 'draft' | 'finished' | 'cancelled'
export type PackSize = 2 | 4

export const PREPARATION_NOTE_MAX_LENGTH = 1000
export const PREPARATION_REASON_MAX_LENGTH = 500

/** A material a preparation uses, with its stock now (a string in the unit's precision). */
export interface PreparationMaterial extends Localized {
  id: string
  item_code: string
  unit: QuantityUnit
  prep_role: PrepRole
  icon_key: string | null
  icon_url: string | null
  archived: boolean
  stock: string
  /** Packaging materials: the prepared twin's stock. */
  prepared_stock: string | null
}

export interface PreparationLine {
  id: string
  pack_size: PackSize | null
  satay_g: string | null
  zip_bag_qty: string | null
  sachets: number | null
  material: PreparationMaterial | null
  quantity: string | null
  /** Unit of `zip_bag_qty` / `quantity`. */
  unit: QuantityUnit | null
}

/** One item a preparation takes or makes. */
export interface PreparationItem extends Localized {
  item_code: string
  unit: QuantityUnit
  quantity: string
  material_id: string | null
  icon_key: string | null
}

export interface Preparation {
  id: string
  code: string
  type: PreparationType
  status: PreparationStatus
  prepared_date: string | null
  note: string | null
  cancel_reason: string | null
  version: number
  lines: PreparationLine[]
  satay_materials: {
    satay_sauce: PreparationMaterial | null
    zip_bag_2: PreparationMaterial | null
    zip_bag_4: PreparationMaterial | null
  } | null
  inputs: PreparationItem[]
  outputs: PreparationItem[]
  created_by: UserRef | null
  created_at: string
  updated_by: UserRef | null
  updated_at: string
  finished_by: UserRef | null
  finished_at: string | null
  cancelled_by: UserRef | null
  cancelled_at: string | null
}

export interface PreparationListItem {
  id: string
  code: string
  type: PreparationType
  status: PreparationStatus
  prepared_date: string | null
  created_at: string
  outputs: PreparationItem[]
  created_by: UserRef | null
}

export interface PreparationStats {
  drafts: number
  finished_this_month: number
  sachets_2_this_month: number
  sachets_4_this_month: number
}

/** A packaging line in a preparation alert's payload. */
export interface PreparationAlertMaterial extends Localized {
  quantity: string
  unit: QuantityUnit
}

// --- Attendance ----------------------------------------------------------------------------------

export type ShiftCode = 'morning' | 'afternoon'
export type AttendanceStatus = 'present' | 'late' | 'absent'
export type CheckoutStatus = 'checked_out' | 'forgot_checkout'
export type AttendanceAction = 'check_in' | 'check_out'
export type ShiftPhase = 'upcoming' | 'check_in_open' | 'in_progress' | 'check_out_open' | 'closed'

/** Instants are ISO strings with the business offset; `timezone` names the zone. */
export interface AttendanceRecord {
  id: string
  user_id: string
  work_date: string
  shift_code: ShiftCode
  workplace_id: string | null
  scheduled_start: string
  scheduled_end: string
  status: AttendanceStatus
  late_minutes: number
  /** Before the scheduled start / after the scheduled end; 0 when its workplace didn't count
   *  them when the record was created (`early_counts` / `overtime_counts`). */
  early_minutes: number
  overtime_minutes: number
  early_counts: boolean
  overtime_counts: boolean
  check_in_at: string | null
  check_in_distance_m: number | null
  check_in_accuracy_m: number | null
  checkout_status: CheckoutStatus | null
  check_out_at: string | null
  check_out_distance_m: number | null
  check_out_accuracy_m: number | null
  source: 'mini_app' | 'auto' | 'correction'
  corrected: boolean
  correction_reason: string | null
  corrected_by: UserRef | null
  corrected_at: string | null
}

export interface WorkplaceBrief {
  id: string
  name: string
  address: string | null
  latitude: number | null
  longitude: number | null
  radius_m: number
  has_coordinates: boolean
}

export interface ShiftDay extends Localized {
  code: ShiftCode
  start: string
  end: string
  check_in_opens: string
  check_in_until: string
  check_out_opens: string
  check_out_until: string
  phase: ShiftPhase
  record: AttendanceRecord | null
}

export interface NextAction {
  action: AttendanceAction | 'none'
  shift_code: ShiftCode | null
  /** The last minute of the open window ("until 07:44"). */
  until: string | null
  closes_at: string | null
  next_action: AttendanceAction | null
  next_shift_code: ShiftCode | null
  next_opens_at: string | null
}

export interface HolidayBrief extends Localized {
  id: string
}

/** Why a day isn't tracked: a holiday (with its names) or a weekday the schedule skips. */
export interface DayOff {
  reason: 'holiday' | 'weekday'
  holidays: HolidayBrief[]
}

export interface AttendanceToday {
  server_time: string
  timezone: string
  work_date: string
  workplace: WorkplaceBrief | null
  /** On a day off: why; `shifts` is then empty and `next_action` points at the next tracked day. */
  day_off: DayOff | null
  shifts: ShiftDay[]
  next_action: NextAction
  /** False: a supervisor whose attendance is switched off (`next_action` is `none`). */
  tracked: boolean
  /** Attendance begins on this date (`next_action` is `none` until then). */
  starts_on: string | null
}

export interface CheckResult {
  action: AttendanceAction
  record: AttendanceRecord
  today: AttendanceToday
}

export interface ShiftKpis {
  expected: number
  present: number
  late: number
  absent: number
  not_yet: number
  no_record: number
  checked_out: number
  forgot_checkout: number
}

export interface AttendanceDayShift extends Localized {
  code: ShiftCode
  start: string
  end: string
  check_in_until: string
  check_out_until: string
  phase: ShiftPhase
  kpis: ShiftKpis
}

export interface AttendanceDayCell {
  /** `day_off`: not tracked that day for the employee (a kept corrected record is `recorded`);
   *  `not_expected`: not one of their shifts (their own schedule). */
  state: 'recorded' | 'not_yet' | 'no_record' | 'day_off' | 'not_expected'
  record: AttendanceRecord | null
  /** "HH:MM": the employee's own times when their schedule is custom. */
  start?: string | null
  end?: string | null
}

export interface WorkplaceRef {
  id: string
  name: string
}

/** `GET /attendance/workplace-options`: active workplaces for the user form and users filter. */
export interface WorkplaceOption extends WorkplaceRef {
  is_default: boolean
}

export interface AttendanceDayRow {
  user: UserRef
  role: Role
  position: string | null
  is_active: boolean
  workplace: WorkplaceRef | null
  day_off: DayOff | null
  shifts: Partial<Record<ShiftCode, AttendanceDayCell>>
  /** "Starts later" rows: the first tracked day. */
  starts_on?: string | null
}

export interface AttendanceDayWorkplace extends WorkplaceRef {
  is_default: boolean
  day_off: DayOff | null
  /** That workplace's own shift times, KPIs for its employees. */
  shifts: AttendanceDayShift[]
}

export interface AttendanceDay {
  date: string
  timezone: string
  server_time: string
  workplace_id: string | null
  /** Of the filtered workplace, else the default one. */
  day_off: DayOff | null
  /** Over every row shown: the filtered workplace's times, else the default's. */
  shifts: AttendanceDayShift[]
  workplaces: AttendanceDayWorkplace[]
  /** Every active workplace (the filter). */
  workplace_options: WorkplaceRef[]
  rows: AttendanceDayRow[]
  /** Not expected that day and in no KPI (cells hold only records already made). */
  starts_later: AttendanceDayRow[]
  not_tracked: AttendanceDayRow[]
}

export interface ShiftWindows {
  check_in_opens: string
  check_in_until: string
  late_after: string
  absent_from: string
  check_out_opens: string
  check_out_until: string
  forgot_from: string
}

export interface AttendanceShift extends Localized {
  code: ShiftCode
  /** "HH:MM" */
  start_time: string
  end_time: string
  position: number
  windows: ShiftWindows
}

export interface AttendanceRules {
  open_before_min: number
  absent_after_min: number
  checkout_window_min: number
  reminders_enabled: boolean
  /** Count early check-ins / overtime as extra time (applies to new records). */
  count_early_checkin: boolean
  count_overtime: boolean
}

export interface WorkplaceEmployee {
  user: UserRef
  role: Role
  position: string | null
}

/** A schedule version: from `effective_from` on, the tracked weekdays (Monday = 1), both shifts
 *  with their windows and the rules. */
export interface ScheduleVersion extends AttendanceRules {
  id: string
  effective_from: string
  weekdays: number[]
  shifts: AttendanceShift[]
  created_by: UserRef | null
  created_at: string
}

/** A workplace with its location and its current schedule (read-only: edited in Scheduling). */
export interface Workplace extends WorkplaceBrief {
  is_default: boolean
  is_active: boolean
  archived_at: string | null
  timezone: string
  schedule: ScheduleVersion
  /** Active staff and supervisors assigned. */
  employee_count: number
  has_history: boolean
  /** Only on `GET /attendance/workplaces/{id}`. */
  employees: WorkplaceEmployee[] | null
  created_by: UserRef | null
  created_at: string
  updated_by: UserRef | null
  updated_at: string
}

export interface ScheduleShiftInput {
  code: ShiftCode
  name_km: string
  name_en: string
  start_time: string
  end_time: string
}

/** Scheduling writes go to the listed workplaces or "all" (every active one, later ones not). */
export type ScheduleTargets = string[] | 'all'

export interface ShiftsInput extends AttendanceRules {
  workplace_ids: ScheduleTargets
  shifts: ScheduleShiftInput[]
  effective_from: string
}

export interface WeekdaysInput {
  workplace_ids: ScheduleTargets
  weekdays: number[]
  effective_from: string
}

export interface SchedulingWorkplace extends WorkplaceOption {
  current: ScheduleVersion
  /** Effective after today, soonest first. */
  upcoming: ScheduleVersion[]
}

export interface Scheduling {
  today: string
  timezone: string
  workplaces: SchedulingWorkplace[]
  /** The chosen workplaces' current weekdays / shifts and rules differ (the page shows the first). */
  differs: { weekdays: boolean; shifts: boolean }
  workplace_options: WorkplaceOption[]
}

export interface SchedulingWriteResult {
  scheduling: Scheduling
  records_removed: number
  absents_recreated: number
  /** Left alone: the employee's month has a pending or approved request. */
  skipped_locked: number
  /** Employees whose own schedule lost a shift the workplace no longer has. */
  affected_employees?: { user_id: string; name: string }[]
}

// --- Employees' own schedules -------------------------------------------------------------------

/** The fields an employee's schedule can set; the others inherit the workplace's. */
export type ScheduleField = 'weekdays' | 'shift_codes' | 'shift_times'

export interface ShiftTime {
  /** "HH:MM" */
  start_time: string
  end_time: string
}

export interface PersonalShift extends Localized, ShiftTime {
  code: ShiftCode
  windows: ShiftWindows
}

/** An employee's schedule on a date: weekdays (Monday = 1), the shifts they work and which
 *  fields are their own (`custom`). */
export interface ScheduleSummary {
  weekdays: number[]
  shifts: PersonalShift[]
  custom: ScheduleField[]
}

/** An override version; a null field inherits the workplace's. */
export interface OverrideVersion {
  id: string
  effective_from: string
  weekdays: number[] | null
  shift_codes: ShiftCode[] | null
  shift_times: Partial<Record<ShiftCode, ShiftTime>> | null
  created_by: UserRef | null
  created_at: string
}

export interface EmployeeScheduleRow {
  user: UserRef
  role: Role
  position: string | null
  workplace: WorkplaceRef | null
  summary: ScheduleSummary
  upcoming: number
  next_change: string | null
}

export interface EmployeeScheduleList {
  today: string
  items: EmployeeScheduleRow[]
  workplace_options: WorkplaceRef[]
}

export interface PreviewShift extends ShiftTime {
  code: ShiftCode
}

export interface PreviewDay {
  date: string
  shifts: PreviewShift[]
  day_off: DayOff | null
  works_on_holiday: HolidayBrief | null
}

export interface EmployeeScheduleDetail {
  user: UserRef
  role: Role
  position: string | null
  workplace: WorkplaceRef | null
  today: string
  schedule: ScheduleSummary
  /** What they inherit: the workplace's schedule today. */
  workplace_schedule: ScheduleSummary
  rules: AttendanceRules
  current: OverrideVersion | null
  upcoming: OverrideVersion[]
  preview: PreviewDay[]
}

/** Missing key = keep the value in effect then; "inherit" = the workplace's. */
export interface EmployeeScheduleInput {
  user_ids: string[]
  effective_from?: string
  weekdays?: number[] | 'inherit'
  shift_codes?: ShiftCode[] | 'inherit'
  shift_times?: Partial<Record<ShiftCode, ShiftTime>> | 'inherit'
}

export interface EmployeeScheduleWriteResult {
  effective_from: string
  changed: string[]
  unchanged: string[]
}

export interface HolidayException {
  id: string
  holiday_id: string
  user: UserRef
  role: Role
  date: string
  shift_codes: ShiftCode[] | null
  shift_times: Partial<Record<ShiftCode, ShiftTime>> | null
  /** What they work that day. */
  shifts: PreviewShift[]
  created_by: UserRef | null
  created_at: string
}

export interface HolidayExceptionInput {
  user_ids: string[]
  dates: string[]
  shift_codes?: ShiftCode[] | null
  shift_times?: Partial<Record<ShiftCode, ShiftTime>> | null
}

export interface HolidayExceptionWriteResult {
  items: HolidayException[]
  records_removed: number
  skipped_locked: number
}

export interface CalendarDay {
  date: string
  /** tracked / off at every chosen workplace, or mixed. */
  status: 'tracked' | 'off' | 'mixed'
  day_off: DayOff | null
  /** Holidays covering any chosen workplace. */
  holidays: HolidayBrief[]
  /** Employees set to work on that holiday day. */
  working?: number
  /** Per workplace when several are chosen. */
  workplaces: { workplace_id: string; day_off: DayOff | null }[] | null
}

export interface AttendanceCalendar {
  year: number
  month: number
  today: string
  workplaces: WorkplaceRef[]
  days: CalendarDay[]
}

export interface Holiday extends HolidayBrief {
  start_date: string
  end_date: string
  days: number
  scope: 'all' | 'selected'
  /** `selected` only. */
  workplaces: WorkplaceRef[]
  note: string | null
  created_by: UserRef | null
  created_at: string
  updated_by: UserRef | null
  updated_at: string
}

export interface HolidayInput {
  name_km: string
  name_en: string
  start_date: string
  end_date: string
  scope: 'all' | 'selected'
  workplace_ids?: string[]
  note: string | null
}

export interface HolidayWriteResult {
  holiday: Holiday | null
  records_removed: number
  absents_recreated: number
  skipped_locked: number
}

export interface HolidayCopyResult {
  created: Holiday[]
  skipped: number
  records_removed: number
  skipped_locked: number
}

// --- Attendance summary (`/attendance/me/summary`, `/attendance/users/{id}/summary`) ----------

export interface AttendanceSummaryShifts {
  total_shifts: number
  by_shift: Partial<Record<ShiftCode, number>>
  minutes: number
}

export interface AttendanceSummaryCount {
  count: number
  minutes: number
}

export interface AttendanceSummaryKpis {
  present: AttendanceSummaryShifts
  absent: AttendanceSummaryShifts
  late: AttendanceSummaryCount
  early: AttendanceSummaryCount
  overtime: AttendanceSummaryCount
  missing_minutes: number
  extra_minutes: number
  /** extra − missing (signed). */
  balance_minutes: number
  forgot_checkout: number
}

export interface AttendanceSummaryDayShift {
  code: ShiftCode
  /** `none`: no record (yet). */
  status: AttendanceStatus | 'none'
  record: AttendanceRecord | null
}

export interface AttendanceSummaryDay {
  date: string
  /** Not tracked that day (records kept there don't count). */
  day_off: DayOff | null
  shifts: AttendanceSummaryDayShift[]
  /** Inside an untracked period: greyed, counted in no KPI. */
  not_tracked?: boolean
}

export interface AttendanceSummary {
  timezone: string
  /** `month` null: the whole year; `end` is at most today. */
  period: { year: number; month: number | null; start: string; end: string }
  employee: {
    user: UserRef
    role: Role
    position: string | null
    is_active: boolean
    workplace: WorkplaceRef | null
    /** The attendance start date (older accounts: creation date): earlier days aren't listed. */
    since: string
  }
  shifts: (Localized & { code: ShiftCode })[]
  kpis: AttendanceSummaryKpis
  /** Newest first, from the period start (or the account's creation) to today. */
  days: AttendanceSummaryDay[]
  /** Monthly periods only: the month's request, its eligibility and the lock (see requests). */
  request: AttendanceRequestBrief | null
  request_eligibility: RequestEligibility | null
  /** A pending or approved request locks the month's records. */
  month_locked: boolean
}


// --- Attendance requests ----------------------------------------------------------------------

export type RequestStatus = 'pending' | 'approved' | 'rejected'
export type RequestType = 'salary_cut' | 'unpaid_work' | 'both'
/** `window_closed` with no request reads "No request". */
export type RequestEligibility = 'eligible' | 'not_needed' | 'window_not_open' | 'window_closed'

/** Same limit as the API. */
export const REQUEST_TEXT_MAX_LENGTH = 500
/** Fewer missing minutes than this need no request. */
export const REQUEST_MIN_MISSING_MINUTES = 60

export interface AttendanceRequestBrief {
  id: string
  status: RequestStatus
  type: RequestType
  requested_salary_cut_minutes: number
  requested_unpaid_work_minutes: number
  /** Null until approved. */
  approved_salary_cut_minutes: number | null
  approved_unpaid_work_minutes: number | null
  approved_with_changes: boolean
  review_comment: string | null
  reject_reason: string | null
  submitted_at: string
  reviewed_by: UserRef | null
  reviewed_at: string | null
}

export interface AttendanceRequest extends AttendanceRequestBrief {
  user: UserRef
  position: string | null
  year: number
  month: number
  /** The month as it was when the request was sent. */
  missing_minutes: number
  extra_minutes: number
  absent_minutes: number
  late_minutes: number
  balance_minutes: number
  note: string | null
  month_locked: boolean
}

export interface MyRequestMonth {
  year: number
  month: number
  balance_minutes: number
  missing_minutes: number
  extra_minutes: number
  absent_minutes: number
  late_minutes: number
  eligibility: RequestEligibility
  /** The window: the 1st of the next month to the deadline day. */
  opens: string
  closes: string
  request: AttendanceRequestBrief | null
}

export interface MyRequests {
  timezone: string
  year: number
  request_deadline_day: number
  /** Newest first, up to the current month. */
  months: MyRequestMonth[]
}

/** A list row: a request, or (`no_request`) an eligible month nobody requested. */
export interface AttendanceRequestRow {
  id: string | null
  status: RequestStatus | 'no_request'
  user: UserRef
  position: string | null
  year: number
  month: number
  type: RequestType | null
  missing_minutes: number
  requested_salary_cut_minutes: number | null
  requested_unpaid_work_minutes: number | null
  approved_salary_cut_minutes: number | null
  approved_unpaid_work_minutes: number | null
  approved_with_changes: boolean
  note: string | null
  submitted_at: string | null
}

export interface AttendanceRequestPage extends Page<AttendanceRequestRow> {
  /** Pending requests in the viewer's scope. */
  pending_count: number
}

export interface AttendanceRequestSettings {
  request_deadline_day: number
}
