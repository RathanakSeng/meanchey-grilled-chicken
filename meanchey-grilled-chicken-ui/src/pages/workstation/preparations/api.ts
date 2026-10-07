import type { QueryClient } from '@tanstack/react-query'
import type { Preparation } from '@/lib/types'
import { invalidateInventory } from '@/pages/workstation/inventory/api'

/** Query keys (see docs/ARCHITECTURE.md). */
export const preparationKeys = {
  list: ['preparations'] as const,
  stats: ['preparations-stats'] as const,
  one: (id: string) => ['preparation', id] as const,
  materialOptions: ['preparations-material-options'] as const,
}

/** After Finish, reopen, cancel or New: the preparation is fresh; lists, figures and stock are
 * refetched (Finish / reopen / cancel move stock). */
export function onPreparationChanged(queryClient: QueryClient, p: Preparation) {
  queryClient.setQueryData(preparationKeys.one(p.id), p)
  void queryClient.invalidateQueries({ queryKey: preparationKeys.list })
  void queryClient.invalidateQueries({ queryKey: preparationKeys.stats })
  void queryClient.invalidateQueries({ queryKey: preparationKeys.materialOptions })
  invalidateInventory(queryClient)
}

/** localStorage key of a preparation's unsaved draft. */
export function preparationDraftKey(id: string) {
  return `mc.prep.${id}`
}
