import { useTranslation } from 'react-i18next'
import { Icon, type IconName } from './icons'
import { cx } from './ui'

export interface Kpi {
  key: string
  label: string
  value: number | undefined
  icon: IconName
  /** Icon tile colors, e.g. 'bg-green-50 text-green-700'. */
  tone: string
  /** Clickable figure (e.g. applies a filter); `selected` outlines it. */
  onClick?(): void
  selected?: boolean
}

// Phones (incl. the Mini App): every card visible at once, no sideways scrolling.
// 3 figures → 3 columns; 4 → 2 × 2 (4 in a row from lg).
const COLUMNS: Record<number, string> = {
  1: 'grid-cols-1',
  2: 'grid-cols-2',
  3: 'grid-cols-3',
  4: 'grid-cols-2 lg:grid-cols-4',
}

/**
 * Figures above a list. Compact on phones (icon and label above the number, labels may wrap to
 * two lines, which Khmer often needs); icon beside the text from `sm` up.
 */
export function KpiGrid({ items, loading }: { items: Kpi[]; loading: boolean }) {
  const { i18n } = useTranslation()
  const format = new Intl.NumberFormat(i18n.language === 'km' ? 'km-KH' : 'en-GB')

  return (
    <div className={cx('mb-4 grid gap-2 sm:gap-3', COLUMNS[items.length] ?? 'grid-cols-2')}>
      {items.map((kpi) => {
        const body = (
          <>
            <span
              className={cx(
                'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg sm:h-10 sm:w-10 sm:rounded-xl',
                kpi.tone,
              )}
            >
              <Icon name={kpi.icon} width={18} height={18} />
            </span>
            <span className="min-w-0 text-left">
              <span className="line-clamp-2 block text-xs font-medium leading-snug text-stone-500">
                {kpi.label}
              </span>
              {loading || kpi.value === undefined ? (
                <span className="mt-1 block h-6 w-10 animate-pulse rounded bg-stone-200" />
              ) : (
                <span className="block text-xl font-semibold tabular-nums text-stone-900 sm:text-2xl">
                  {format.format(kpi.value)}
                </span>
              )}
            </span>
          </>
        )
        const className = cx(
          'flex min-w-0 flex-col items-start gap-2 rounded-xl bg-white p-3 shadow-sm ring-1 transition sm:flex-row sm:items-center sm:gap-3 sm:p-4',
          kpi.selected ? 'ring-2 ring-brand-500' : 'ring-stone-200',
        )
        return kpi.onClick ? (
          <button
            key={kpi.key}
            type="button"
            aria-pressed={kpi.selected}
            onClick={kpi.onClick}
            className={cx(
              className,
              'hover:ring-brand-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500',
            )}
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
