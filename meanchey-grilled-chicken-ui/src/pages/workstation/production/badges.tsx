import { useTranslation } from 'react-i18next'
import { Badge, cx } from '@/components/ui'
import type { BatchStatus, ProductionBatchListItem } from '@/lib/types'

const STATUS_TONES = { in_progress: 'amber', completed: 'green', cancelled: 'neutral' } as const

export function BatchStatusBadge({ status }: { status: BatchStatus }) {
  const { t } = useTranslation()
  return <Badge tone={STATUS_TONES[status]}>{t(`production.status.${status}`)}</Badge>
}

/** ●●○: one dot per step (filled when finished, ringed when being filled in). */
export function StepDots({ steps }: { steps: ProductionBatchListItem['steps'] }) {
  const { t } = useTranslation()
  const done = steps.filter((s) => s === 'finished').length
  return (
    <span
      className="inline-flex items-center gap-1"
      role="img"
      aria-label={t('production.stepsDone', { count: done })}
      title={t('production.stepsDone', { count: done })}
    >
      {steps.map((s, i) => (
        <span
          key={i}
          className={cx(
            'h-2.5 w-2.5 rounded-full',
            s === 'finished' ? 'bg-green-600' : s === 'draft' ? 'bg-white ring-2 ring-amber-400' : 'bg-stone-200',
          )}
        />
      ))}
    </span>
  )
}
