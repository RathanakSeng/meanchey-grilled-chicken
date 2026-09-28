import { useQuery } from '@tanstack/react-query'
import { usePermission } from '@/auth/usePermission'
import { api } from './api'

export const POSITIONS_QUERY_KEY = ['user-positions'] as const

/** Distinct staff positions in the viewer's scope — for suggestions and the list filter. */
export function usePositions() {
  const canView = usePermission('users.view')
  return useQuery({
    queryKey: POSITIONS_QUERY_KEY,
    queryFn: async () => (await api.get<string[]>('/users/positions')).data,
    enabled: canView,
    staleTime: 60_000,
  })
}

/** Same normalization as the API: trim and collapse whitespace; case and script kept. */
export function normalizePosition(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}
