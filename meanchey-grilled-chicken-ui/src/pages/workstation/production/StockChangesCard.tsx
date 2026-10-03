import { useTranslation } from 'react-i18next'
import { Card, cx } from '@/components/ui'
import { useLocalized } from '@/lib/format'
import type { ProductionBatch } from '@/lib/types'
import { deltaTone, useStockFormat } from '@/pages/workstation/inventory/api'
import { STEPS } from './api'

/**
 * What each finished step of this batch added to / removed from the inventory (reversed steps
 * left out). Batches from before inventory existed say they aren't counted. Only with
 * inventory.history: the API sends the fields only then.
 */
export function StockChangesCard({ batch }: { batch: ProductionBatch }) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const fmt = useStockFormat()

  const changes = batch.stock_changes
  if (changes === undefined) return null
  if (!batch.inventory_tracked) {
    return <p className="mt-4 text-sm text-stone-500">{t('inventory.untracked')}</p>
  }
  if (changes.length === 0) return null
  const steps = STEPS.filter(({ n }) => changes.some((c) => c.step === n))

  return (
    <Card title={t('inventory.stockChanges')} className="mt-4">
      <div className="-my-1 space-y-3">
        {steps.map(({ n, labelKey }) => (
          <div key={n}>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-stone-500">
              {t('audit.productionStep', { step: n, name: t(labelKey) })}
            </h3>
            <ul className="divide-y divide-stone-100 text-sm">
              {changes
                .filter((c) => c.step === n)
                .map((c) => (
                  <li key={c.item_code} className="flex items-baseline justify-between gap-3 py-1.5">
                    <span className="min-w-0 text-stone-800">
                      {c.section === 'wasted' && (
                        <span className="text-stone-500">{t('inventory.sections.wasted')}: </span>
                      )}
                      {localized(c)}
                    </span>
                    <span className="shrink-0 font-medium tabular-nums">
                      {c.count_delta !== null && (
                        <span className={cx('mr-2', deltaTone(c.count_delta))}>
                          {fmt.count(c.count_delta, true)}
                        </span>
                      )}
                      {c.kg_delta !== null && (
                        <span
                          className={deltaTone(c.kg_delta)}
                          title={c.kg_estimated ? t('inventory.estimatedHint') : undefined}
                        >
                          {c.kg_estimated && '≈ '}
                          {fmt.kg(c.kg_delta, true)}
                        </span>
                      )}
                    </span>
                  </li>
                ))}
            </ul>
          </div>
        ))}
      </div>
    </Card>
  )
}
