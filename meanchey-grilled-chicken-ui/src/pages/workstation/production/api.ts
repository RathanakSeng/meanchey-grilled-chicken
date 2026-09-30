import type { QueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '@/lib/api'
import { tokenStore } from '@/lib/storage'
import type { ProductionBatch, StepNumber, StepSlug } from '@/lib/types'
import { invalidatePlans } from '@/pages/workstation/production-plans/api'

/** Query keys (see docs/ARCHITECTURE.md). */
export const productionKeys = {
  list: ['production'] as const,
  stats: ['production-stats'] as const,
  batch: (id: string) => ['production-batch', id] as const,
  supplierOptions: (q: string) => ['production-supplier-options', q] as const,
}

/** `dateKey` / `dateShortKey`: the step's date label (ថ្ងៃនាំចូល…) and its short form (នាំចូល…). */
export const STEPS: { n: StepNumber; slug: StepSlug; labelKey: string; dateKey: string; dateShortKey: string }[] = [
  {
    n: 1,
    slug: 'raw-material',
    labelKey: 'production.steps.rawMaterial',
    dateKey: 'production.dates.import',
    dateShortKey: 'production.datesShort.import',
  },
  {
    n: 2,
    slug: 'produced',
    labelKey: 'production.steps.produced',
    dateKey: 'production.dates.production',
    dateShortKey: 'production.datesShort.production',
  },
  {
    n: 3,
    slug: 'standardize',
    labelKey: 'production.steps.standardize',
    dateKey: 'production.dates.packing',
    dateShortKey: 'production.datesShort.packing',
  },
]

export function slugOf(step: StepNumber): StepSlug {
  return STEPS[step - 1].slug
}

/** The step's data, or null while it hasn't started (the previous step was never finished). */
export function stepData(batch: ProductionBatch, step: StepNumber) {
  return step === 1 ? batch.raw_material : step === 2 ? batch.produced : batch.standardize
}

/** The step's date, recorded by the server when it was finished (null while a draft). */
export function stepDate(batch: ProductionBatch, step: StepNumber): string | null {
  return step === 1
    ? batch.raw_material.import_date
    : step === 2
      ? (batch.produced?.production_date ?? null)
      : (batch.standardize?.packaging_date ?? null)
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
  // Finishing / reopening steps creates or resets the packaging plan.
  invalidatePlans(queryClient, batch.id)
}

/** Step 3 can be saved and finished only once the packaging plan is confirmed. */
export function planConfirmed(batch: ProductionBatch): boolean {
  return batch.plan?.status === 'confirmed'
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
