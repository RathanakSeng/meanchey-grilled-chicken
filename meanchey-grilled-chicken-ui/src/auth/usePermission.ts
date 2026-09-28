import type { Role } from '@/lib/types'
import { useAuth } from './AuthProvider'

/** UX only — the API is the source of truth for authorization. */
export function usePermission(code: string): boolean {
  const { me } = useAuth()
  return me?.permissions.includes(code) ?? false
}

export function useHasRole(...roles: Role[]): boolean {
  const { me } = useAuth()
  return me ? roles.includes(me.user.role) : false
}

export interface AccessRule {
  /** Required permission code. */
  permission?: string
  /** Allowed roles. */
  roles?: Role[]
}

export function useCanAccess() {
  const { me } = useAuth()
  return ({ permission, roles }: AccessRule): boolean => {
    if (!me) return false
    if (permission && !me.permissions.includes(permission)) return false
    if (roles && !roles.includes(me.user.role)) return false
    return true
  }
}
