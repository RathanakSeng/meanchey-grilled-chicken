import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { cx } from '@/components/ui'
import { useFormatDate, useLocalized } from '@/lib/format'
import { paths } from '@/lib/paths'
import type { InventoryMovement } from '@/lib/types'
import { STEPS } from '@/pages/workstation/production/api'
import { deltaTone, useStockFormat } from './api'

/**
 * One stock movement: item (unless `showItem` is false, e.g. inside that item's sheet), the
 * signed change (green / red, "≈" when estimated), the balance after it, the source (batch link
 * and step, reversal, or adjustment and reason) and who made it.
 */
export function MovementRow({
  movement: m,
  showItem = true,
}: {
  movement: InventoryMovement
  showItem?: boolean
}) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const formatDate = useFormatDate()
  const fmt = useStockFormat()
  const by = m.created_by && !m.created_by.is_system ? m.created_by.full_name : t('audit.system')
  const stepName = m.step ? t(STEPS[m.step - 1].labelKey) : ''

  const orderLink = m.order && (
    <Link to={paths.order(m.order.id)} className="font-medium tabular-nums text-brand-700 hover:underline">
      {m.order.code}
    </Link>
  )
  const batchLink = m.batch && (
    <Link
      to={paths.productionBatch(m.batch.id, m.step ?? undefined)}
      className="tabular-nums text-stone-600 hover:underline"
    >
      {m.batch.code}
    </Link>
  )
  const source =
    m.source === 'order' || m.source === 'order_return' ? (
      // "Order OR-… · from PR-…" / "Return OR-… · to PR-…" (the batch it is attributed to).
      <>
        {t(m.source === 'order' ? 'inventory.sources.order' : 'inventory.sources.order_return')} {orderLink}
        {batchLink && (
          <span>
            {' · '}
            {t(m.source === 'order' ? 'inventory.fromBatch' : 'inventory.toBatch')} {batchLink}
          </span>
        )}
      </>
    ) : m.source === 'adjustment' ? (
      <>
        {t('inventory.sources.adjustment')}
        {m.reason && <span className="text-stone-500"> — {m.reason}</span>}
      </>
    ) : (
      <>
        {m.reversal_of !== null && (
          <span className="mr-1 font-medium text-stone-700">
            {t(m.reason === 'cancel' ? 'inventory.reversedCancel' : 'inventory.reversedReopen')} ·
          </span>
        )}
        {m.batch ? (
          <Link
            to={paths.productionBatch(m.batch.id, m.step ?? undefined)}
            className="font-medium tabular-nums text-brand-700 hover:underline"
          >
            {m.batch.code}
          </Link>
        ) : (
          t('inventory.sources.production')
        )}
        {stepName && <span> · {stepName}</span>}
      </>
    )

  return (
    <li className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:gap-4">
      <div className="min-w-0 flex-1">
        {showItem && (
          <p className="font-medium text-stone-900">
            {m.section === 'wasted' && (
              <span className="text-stone-500">{t('inventory.sections.wasted')}: </span>
            )}
            {localized(m)}
          </p>
        )}
        <p className="text-sm text-stone-600">{source}</p>
        <p className="text-xs text-stone-400">
          {formatDate(m.created_at)} · {by}
        </p>
      </div>
      <div className="flex shrink-0 items-baseline gap-4 tabular-nums sm:flex-col sm:items-end sm:gap-0">
        <span className="font-semibold">
          {m.count_delta !== null && (
            <span className={cx('mr-2', deltaTone(m.count_delta))}>{fmt.count(m.count_delta, true)}</span>
          )}
          {m.kg_delta !== null && (
            <span className={deltaTone(m.kg_delta)} title={m.kg_estimated ? t('inventory.estimatedHint') : undefined}>
              {m.kg_estimated && '≈ '}
              {fmt.kg(m.kg_delta, true)}
            </span>
          )}
        </span>
        <span className="text-xs text-stone-500">
          {t('inventory.balanceAfter', {
            value: [
              m.balance_count_after !== null && fmt.count(m.balance_count_after),
              m.balance_kg_after !== null && fmt.kg(m.balance_kg_after),
            ]
              .filter(Boolean)
              .join(' · '),
          })}
        </span>
      </div>
    </li>
  )
}
