import { useQuery, type QueryClient } from '@tanstack/react-query'
import { usePermission } from '@/auth/usePermission'
import { api } from './api'
import type { RoleCapacity, Role } from './types'

export const ROLE_CAPACITY_KEY = ['role-capacity'] as const
export const ROLE_LIMITS_KEY = ['role-limits'] as const

/**
 * Active users and limit per role the viewer manages (`GET /users/role-capacity`), for the create
 * form, the role change sheet and the users list. Needs `users.view` or `users.create`.
 */
export function useRoleCapacity() {
  const canView = usePermission('users.view')
  const canCreate = usePermission('users.create')
  const query = useQuery({
    queryKey: ROLE_CAPACITY_KEY,
    queryFn: async () => (await api.get<RoleCapacity[]>('/users/role-capacity')).data,
    enabled: canView || canCreate,
    staleTime: 30_000,
  })
  const byRole = (role: Role): RoleCapacity | undefined => query.data?.find((c) => c.role === role)
  return { ...query, byRole }
}

/** After a user is created, (re)activated, deactivated or changes role. */
export function invalidateRoleCapacity(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: ROLE_CAPACITY_KEY })
  void queryClient.invalidateQueries({ queryKey: ROLE_LIMITS_KEY })
}
