import type { QueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '@/lib/api'
import { tokenStore } from '@/lib/storage'
import type { ProductionBatch, StepNumber, StepSlug } from '@/lib/types'

/** Query keys (see docs/ARCHITECTURE.md). */
export const productionKeys = {
  list: ['production'] as const,
  stats: ['production-stats'] as const,
  batch: (id: string) => ['production-batch', id] as const,
  supplierOptions: (q: string) => ['production-supplier-options', q] as const,
}

export const STEPS: { n: StepNumber; slug: StepSlug; labelKey: string }[] = [
  { n: 1, slug: 'raw-material', labelKey: 'production.steps.rawMaterial' },
  { n: 2, slug: 'produced', labelKey: 'production.steps.produced' },
  { n: 3, slug: 'standardize', labelKey: 'production.steps.standardize' },
]

export function slugOf(step: StepNumber): StepSlug {
  return STEPS[step - 1].slug
}

/** The step's data, or null while it hasn't started (the previous step was never finished). */
export function stepData(batch: ProductionBatch, step: StepNumber) {
  return step === 1 ? batch.raw_material : step === 2 ? batch.produced : batch.standardize
}

/** Any finished step can be reopened unless the batch is cancelled; the API lists which steps
 * that puts back to draft (`reopens_steps`: it and every later finished step). */
export function canReopenStep(batch: ProductionBatch, step: StepNumber): boolean {
  // `?.` on reopens_steps too: an older API without the field must not crash the page.
  return (stepData(batch, step)?.reopens_steps?.length ?? 0) > 0
}

/** After any change: the batch itself is fresh; lists and figures are refetched. */
export function onBatchChanged(queryClient: QueryClient, batch: ProductionBatch) {
  queryClient.setQueryData(productionKeys.batch(batch.id), batch)
  void queryClient.invalidateQueries({ queryKey: productionKeys.list })
  void queryClient.invalidateQueries({ queryKey: productionKeys.stats })
}

/**
 * A draft save that survives the page being hidden or closed (`keepalive`), for
 * `visibilitychange` / `pagehide` / Telegram `deactivated`. Axios can't send keepalive requests,
 * so this uses fetch with the same bearer token. A 401 here isn't refreshed; the local backup
 * covers it and is resent on the next visit.
 */
export function keepaliveSave(batchId: string, slug: StepSlug, body: object): Promise<Response> {
  const token = tokenStore.getAccess()
  return fetch(`${API_BASE_URL}/production/${batchId}/${slug}`, {
    method: 'PATCH',
    keepalive: true,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  })
}
