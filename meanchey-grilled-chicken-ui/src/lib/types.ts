export type Role = 'superadmin' | 'general_manager' | 'supervisor' | 'staff'
export type Language = 'km' | 'en'

export const ROLES: Role[] = ['superadmin', 'general_manager', 'supervisor', 'staff']
/** Staff job title: free text, a label only (never used for access). Same limit as the API. */
export const POSITION_MAX_LENGTH = 50
export const LANGUAGES: Language[] = ['km', 'en']

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
  created_by: string | null
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
}

export interface UserPermissionModule extends Localized {
  module: string
  permissions: UserPermission[]
}

export interface UserPermissions {
  user_id: string
  modules: UserPermissionModule[]
}

export interface AuditUserRef {
  id: string
  full_name: string
  role: Role
  telegram_username: string | null
}

export interface AuditLog {
  id: number
  action: string
  actor: AuditUserRef | null
  target: AuditUserRef | null
  details: Record<string, unknown>
  created_at: string
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> }
}
