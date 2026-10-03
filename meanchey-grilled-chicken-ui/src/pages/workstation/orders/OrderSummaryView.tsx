import { useTranslation } from 'react-i18next'
import { Icon } from '@/components/icons'
import { cx } from '@/components/ui'
import { useLocalized } from '@/lib/format'
import type { BoxColor, Localized, OrderSummary, OrderUnit } from '@/lib/types'
import { amountOf, useAmountFormat } from './api'
import { BoxColorLabel } from './badges'

/** One item in a summary: its amount as an integer (count, or grams). */
export interface SummaryRow extends Localized {
  item_code: string
  unit: OrderUnit
  amount: number
}

export interface SummaryModel {
  colors: { color: BoxColor; boxes: number; items: SummaryRow[] }[]
  total: { boxes: number; items: SummaryRow[] }
}

/** The API's summary in the same shape as the form's live one. */
export function fromApi(summary: OrderSummary): SummaryModel {
  const rows = (items: OrderSummary['total']['items']) =>
    items.map((i) => ({ ...i, amount: amountOf(i) }))
  return {
    colors: summary.colors.map((c) => ({ ...c, items: rows(c.items) })),
    total: { boxes: summary.total.boxes, items: rows(summary.total.items) },
  }
}

function Rows({ items, strong }: { items: SummaryRow[]; strong?: boolean }) {
  const localized = useLocalized()
  const format = useAmountFormat()
  return (
    <dl className="space-y-1 text-sm">
      {items.map((row) => (
        <div key={row.item_code} className="flex items-baseline justify-between gap-3">
          <dt className={cx('min-w-0', strong ? 'text-stone-800' : 'text-stone-600')}>{localized(row)}</dt>
          <dd className={cx('shrink-0 tabular-nums', strong ? 'font-semibold text-stone-900' : 'text-stone-800')}>
            {format(row.unit, row.amount)}
          </dd>
        </div>
      ))}
    </dl>
  )
}

/**
 * Per colour (boxes, 4-packs, 2-packs, kg per by-product) and the grand total. With `available`
 * (item code → amount in stock), totals above the stock get an amber line
 * ("Only 12 × 4-Piece Packs in stock").
 */
export function OrderSummaryView({
  summary,
  available,
}: {
  summary: SummaryModel
  available?: Record<string, number>
}) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const format = useAmountFormat()
  if (summary.total.boxes === 0) {
    return <p className="text-sm text-stone-500">{t('orders.summaryEmpty')}</p>
  }
  const short = available
    ? summary.total.items.filter((row) => row.amount > (available[row.item_code] ?? 0))
    : []
  return (
    <div className="space-y-4">
      {summary.colors.map((c) => (
        <div key={c.color}>
          <p className="mb-1.5 text-sm font-medium text-stone-900">
            <BoxColorLabel color={c.color} count={c.boxes} />
          </p>
          <Rows items={c.items} />
        </div>
      ))}
      <div className="border-t border-stone-200 pt-3">
        <p className="mb-1.5 flex items-baseline justify-between text-sm font-semibold text-stone-900">
          <span>{t('orders.grandTotal')}</span>
          <span className="tabular-nums">{t('orders.boxesCount', { count: summary.total.boxes })}</span>
        </p>
        <Rows items={summary.total.items} strong />
      </div>
      {short.length > 0 && (
        <ul className="space-y-1 rounded-lg bg-amber-50 p-2 text-sm text-amber-900 ring-1 ring-inset ring-amber-200">
          {short.map((row) => (
            <li key={row.item_code} className="flex items-start gap-1.5">
              <Icon name="alert" width={16} height={16} className="mt-0.5 shrink-0" />
              {t('orders.onlyInStock', {
                amount: format(row.unit, available?.[row.item_code] ?? 0),
                name: localized(row),
              })}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
