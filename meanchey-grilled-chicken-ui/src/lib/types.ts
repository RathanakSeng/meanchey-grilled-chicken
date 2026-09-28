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

/** Non-user record an audit entry is about. `name` is its current name (or the logged one). */
export interface AuditEntityRef {
  type: PartnerEntityType | string
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
export type FeatureLevel = 'off' | 'view' | 'full'
export type FeatureMenu = 'production' | 'settings'

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
