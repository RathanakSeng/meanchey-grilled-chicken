import type { Role } from './types'

/**
 * Role checks that involve the superadmin, in one place. The API already shows the superadmin as
 * "System" to everyone else, and its role label is "System" too (roles.superadmin).
 */

export function isSuperadmin(role: Role | null | undefined): boolean {
  return role === 'superadmin'
}

/** The superadmin's login name (its password-equals-username check). */
export const SUPERADMIN_LOGIN = 'superadmin'

/** Who may open the audit log. */
export const AUDIT_ROLES: Role[] = ['superadmin', 'general_manager']
