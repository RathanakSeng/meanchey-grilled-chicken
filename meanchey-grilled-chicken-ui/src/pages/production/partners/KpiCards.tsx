import { useTranslation } from 'react-i18next'
import { Icon, type IconName } from '@/components/icons'
import { cx } from '@/components/ui'
import type { PartnerStats } from '@/lib/types'

export type PartnerStatus = 'active' | 'inactive' | 'all'

interface Kpi {
  key: keyof PartnerStats
  labelKey: string
  icon: IconName
  /** Clicking the card applies this status filter (none: informational only). */
  status?: PartnerStatus
  tone: string
}

const KPIS: Kpi[] = [
  {
    key: 'total_active',
    labelKey: 'partners.kpi.active',
    icon: 'check',
    status: 'active',
    tone: 'bg-green-50 text-green-700',
  },
  {
    key: 'new_this_month',
    labelKey: 'partners.kpi.newThisMonth',
    icon: 'plus',
    tone: 'bg-brand-50 text-brand-600',
  },
  {
    key: 'inactive',
    labelKey: 'partners.kpi.inactive',
    icon: 'archive',
    status: 'inactive',
    tone: 'bg-stone-100 text-stone-600',
  },
]

/** Three figures above the list. 3 in a row on desktop, a horizontal scroller on mobile. */
export function KpiCards({
  stats,
  loading,
  status,
  onStatus,
}: {
  stats: PartnerStats | undefined
  loading: boolean
  status: PartnerStatus
  onStatus(status: PartnerStatus): void
}) {
  const { t, i18n } = useTranslation()
  const format = new Intl.NumberFormat(i18n.language === 'km' ? 'km-KH' : 'en-GB')

  return (
    <div className="scrollbar-none -mx-4 mb-4 flex snap-x gap-3 overflow-x-auto px-4 py-1 sm:mx-0 sm:grid sm:grid-cols-3 sm:overflow-visible sm:px-0 sm:py-0">
      {KPIS.map((kpi) => {
        const selected = kpi.status !== undefined && kpi.status === status
        const body = (
          <>
            <span
              className={cx(
                'inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl',
                kpi.tone,
              )}
            >
              <Icon name={kpi.icon} />
            </span>
            <span className="min-w-0 text-left">
              <span className="block truncate text-xs font-medium text-stone-500">
                {t(kpi.labelKey)}
              </span>
              {loading || !stats ? (
                <span className="mt-1 block h-6 w-12 animate-pulse rounded bg-stone-200" />
              ) : (
                <span className="block text-2xl font-semibold tabular-nums text-stone-900">
                  {format.format(stats[kpi.key])}
                </span>
              )}
            </span>
          </>
        )
        const className = cx(
          'flex min-w-[11rem] shrink-0 snap-start items-center gap-3 rounded-xl bg-white p-4 shadow-sm ring-1 transition sm:min-w-0',
          selected ? 'ring-2 ring-brand-500' : 'ring-stone-200',
        )
        return kpi.status ? (
          <button
            key={kpi.key}
            type="button"
            aria-pressed={selected}
            onClick={() => onStatus(kpi.status!)}
            className={cx(className, 'hover:ring-brand-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500')}
          >
            {body}
          </button>
        ) : (
          <div key={kpi.key} className={className}>
            {body}
          </div>
        )
      })}
    </div>
  )
}
