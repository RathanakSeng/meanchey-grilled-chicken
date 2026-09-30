import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui'
import type { BatchStatus, PlanStatus } from '@/lib/types'

/** Where a plan stands: waiting to be set, confirmed (step 3 may start), or the batch is done. */
export type PlanStage = 'pending' | 'confirmed' | 'completed' | 'cancelled'

export function planStage(status: PlanStatus, batchStatus: BatchStatus): PlanStage {
  if (batchStatus === 'completed' || batchStatus === 'cancelled') return batchStatus
  return status
}

const TONES = { pending: 'amber', confirmed: 'blue', completed: 'green', cancelled: 'neutral' } as const

export function PlanStatusBadge({ stage }: { stage: PlanStage }) {
  const { t } = useTranslation()
  return <Badge tone={TONES[stage]}>{t(`plans.stage.${stage}`)}</Badge>
}

/** "7 × 4-piece · 5 × 2-piece", or "—" while not set. */
export function PlannedPacks({ big, small }: { big: number | null; small: number | null }) {
  const { t } = useTranslation()
  if (big === null && small === null) return <span className="text-stone-400">—</span>
  return <>{t('plans.packsShort', { big: big ?? '—', small: small ?? '—' })}</>
}
