import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAutosave, type AutosaveTarget } from '@/lib/useAutosave'
import type { ProductionBatch, StepNumber } from '@/lib/types'
import { keepaliveSave, productionKeys, slugOf, stepData } from './api'

export { AUTOSAVE_DELAY_MS, type LocalDraft, type SaveStatus } from '@/lib/useAutosave'

interface Options<V> {
  batch: ProductionBatch
  step: StepNumber
  /** Only a draft step the user may edit is autosaved (never a finished one). */
  enabled: boolean
  values: V
  setValues(values: V): void
  /** Form values from the server copy. */
  fromBatch(batch: ProductionBatch): V
  /** Draft body without `version`; invalid inputs are left out (the server keeps its value). */
  toPayload(values: V): Record<string, unknown>
  onSaved(batch: ProductionBatch): void
}

export function draftKey(batchId: string, step: StepNumber) {
  return `mc.draft.${batchId}.${step}`
}

/**
 * Autosave for one production step: the shared draft autosave (`lib/useAutosave.ts`, see
 * docs/ARCHITECTURE.md, "Autosave") pointed at `PATCH /production/{id}/{step}`, with the batch
 * `version` and `409 PRODUCTION_CONFLICT`.
 */
export function useAutosaveDraft<V>(options: Options<V>) {
  const { batch, step } = options
  const queryClient = useQueryClient()
  const slug = slugOf(step)
  const target: AutosaveTarget<ProductionBatch> = {
    storageKey: draftKey(batch.id, step),
    entity: batch,
    version: (b) => b.version,
    updatedAt: (b) => stepData(b, step)?.updated_at ?? b.updated_at,
    editable: (b) => {
      const data = stepData(b, step)
      return b.status === 'in_progress' && !!data && data.status !== 'finished'
    },
    save: async (body) =>
      (await api.patch<ProductionBatch>(`/production/${batch.id}/${slug}`, body)).data,
    keepalive: (body) => keepaliveSave(batch.id, slug, body),
    conflictCode: 'PRODUCTION_CONFLICT',
    conflictEntity: (details) => details.batch as ProductionBatch | undefined,
    reload: () => void queryClient.invalidateQueries({ queryKey: productionKeys.batch(batch.id) }),
  }
  return useAutosave<ProductionBatch, V>({
    target,
    enabled: options.enabled,
    values: options.values,
    setValues: options.setValues,
    fromEntity: options.fromBatch,
    toPayload: options.toPayload,
    onSaved: options.onSaved,
  })
}
