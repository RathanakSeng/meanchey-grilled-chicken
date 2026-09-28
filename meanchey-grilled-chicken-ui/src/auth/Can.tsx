import type { ReactNode } from 'react'
import { useCanAccess, type AccessRule } from './usePermission'

interface CanProps extends AccessRule {
  children: ReactNode
  fallback?: ReactNode
}

/**
 * Render children only if the current user holds the permission (and/or role).
 *
 *   <Can permission="users.create"><Button>New user</Button></Can>
 */
export function Can({ permission, roles, children, fallback = null }: CanProps) {
  const canAccess = useCanAccess()
  return <>{canAccess({ permission, roles }) ? children : fallback}</>
}
