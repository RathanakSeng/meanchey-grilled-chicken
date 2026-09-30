import { useQuery, type QueryClient } from '@tanstack/react-query'
import { usePermission } from '@/auth/usePermission'
import { api } from '@/lib/api'
import type { PlanDetail, PlanPage } from '@/lib/types'

/** Query keys (see docs/ARCHITECTURE.md). Kept out of the lazy page chunk: the nav badge uses it. */
export const planKeys = {
  list: ['production-plans'] as const,
  pending: ['production-plans-pending'] as const,
  detail: (batchId: string) => ['production-plan', batchId] as const,
}

/** Planned pieces of each kind: a 4-piece pack uses 2 wings + 2 thighs, a 2-piece pack 1 + 1. */
export function plannedPieces(big: number | null, small: number | null): number {
  return 2 * (big ?? 0) + (small ?? 0)
}

/**
 * Plans waiting to be set (the nav / hub badge). One small request, refreshed every minute and
 * on focus; nothing is fetched without `production_plan.view`.
 */
export function usePendingPlanCount(): number {
  const canView = usePermission('production_plan.view')
  const query = useQuery({
    queryKey: planKeys.pending,
    queryFn: async () =>
      (await api.get<PlanPage>('/production-plans', { params: { page_size: 1 } })).data.pending_count,
    enabled: canView,
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
  return canView ? (query.data ?? 0) : 0
}

/** After a plan or a step changed: plan lists, the badge and that plan are refetched. */
export function invalidatePlans(queryClient: QueryClient, batchId?: string) {
  void queryClient.invalidateQueries({ queryKey: planKeys.list })
  void queryClient.invalidateQueries({ queryKey: planKeys.pending })
  if (batchId) void queryClient.invalidateQueries({ queryKey: planKeys.detail(batchId) })
}

export async function fetchPlan(batchId: string): Promise<PlanDetail> {
  return (await api.get<PlanDetail>(`/production-plans/${batchId}`)).data
}
