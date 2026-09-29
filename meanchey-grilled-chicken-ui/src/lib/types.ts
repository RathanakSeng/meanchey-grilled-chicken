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
  /** Settable levels, in order (always starts with `off`). */
  levels: FeatureLevel[]
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
  byproducts: BatchByproduct[]
  computed: { wings_count: number; thighs_count: number; yield_percent: string | null }
  catalog: { byproducts: ByproductCatalogItem[]; material_kinds: MaterialKind[] }
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

/** Same limits as the API. */
export const PRODUCTION_COMMENT_MAX_LENGTH = 1000
export const CANCEL_REASON_MAX_LENGTH = 500
