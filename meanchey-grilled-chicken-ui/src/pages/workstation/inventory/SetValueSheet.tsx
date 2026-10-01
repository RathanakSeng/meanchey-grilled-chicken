import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Sheet } from '@/components/Sheet'
import { Alert, Button, Field, Input, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useLocalized } from '@/lib/format'
import { INVENTORY_REASON_MAX_LENGTH, type InventoryItem } from '@/lib/types'
import {
  KG_PLACES,
  formatScaled,
  parseCount,
  parseDecimal,
  scaledOf,
  toInput,
} from '@/pages/workstation/production/numbers'
import { deltaTone, invalidateInventory, useStockFormat } from './api'

/**
 * "Set value" for one item (inventory.adjust): the counted stock replaces the balance, with a
 * required reason. Shows the current value and the difference before saving.
 */
export function SetValueSheet({ item, onClose }: { item: InventoryItem | null; onClose(): void }) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const errorMessage = useErrorMessage()
  const queryClient = useQueryClient()
  const fmt = useStockFormat()
  const [count, setCount] = useState('')
  const [kg, setKg] = useState('')
  const [reason, setReason] = useState('')

  useEffect(() => {
    if (!item) return
    setCount(item.count === null ? '' : String(item.count))
    setKg(toInput(item.kg))
    setReason('')
  }, [item])

  const save = useMutation({
    mutationFn: async (body: { count?: number; kg?: string; reason: string }) =>
      (await api.post<InventoryItem>(`/inventory/items/${item?.code}/set`, body)).data,
    onSuccess: () => {
      invalidateInventory(queryClient)
      onClose()
    },
  })

  if (!item) return null
  const parsedCount = item.tracks_count ? parseCount(count) : null
  const parsedKg = item.tracks_kg ? parseDecimal(kg, KG_PLACES) : null
  const invalid =
    parsedCount?.kind === 'invalid' ||
    parsedKg?.kind === 'invalid' ||
    (parsedCount?.kind !== 'ok' && parsedKg?.kind !== 'ok')
  const countDiff = parsedCount?.kind === 'ok' ? parsedCount.value - (item.count ?? 0) : null
  const kgDiff =
    parsedKg?.kind === 'ok' ? parsedKg.value - (scaledOf(item.kg, KG_PLACES) ?? 0) : null
  const unchanged = !countDiff && !kgDiff

  const submit = () => {
    const body: { count?: number; kg?: string; reason: string } = { reason: reason.trim() }
    if (parsedCount?.kind === 'ok') body.count = parsedCount.value
    if (parsedKg?.kind === 'ok') body.kg = formatScaled(parsedKg.value, KG_PLACES)
    save.mutate(body)
  }

  return (
    <Sheet
      open
      title={t('inventory.setValueTitle', { item: localized(item) })}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose} disabled={save.isPending}>
            {t('common.cancel')}
          </Button>
          <Button
            loading={save.isPending}
            disabled={invalid || unchanged || !reason.trim()}
            onClick={submit}
          >
            {t('common.save')}
          </Button>
        </div>
      }
    >
      <p className="mb-4 text-sm text-stone-600">{t('inventory.setValueBody')}</p>
      <dl className="mb-4 grid grid-cols-2 gap-3 rounded-lg bg-stone-50 p-3 text-sm">
        <dt className="text-stone-500">{t('inventory.current')}</dt>
        <dd className="text-right font-medium tabular-nums text-stone-900">
          {[
            item.count !== null && fmt.count(item.count),
            item.kg !== null && fmt.kg(item.kg),
          ]
            .filter(Boolean)
            .join(' · ')}
        </dd>
      </dl>
      <div className="space-y-3">
        {item.tracks_count && (
          <Field label={t('inventory.newCount')}>
            {(id) => (
              <Input
                id={id}
                inputMode="numeric"
                value={count}
                onChange={(e) => setCount(e.target.value)}
                aria-invalid={parsedCount?.kind === 'invalid'}
              />
            )}
          </Field>
        )}
        {item.tracks_kg && (
          <Field label={t('inventory.newKg')}>
            {(id) => (
              <Input
                id={id}
                inputMode="decimal"
                value={kg}
                onChange={(e) => setKg(e.target.value)}
                aria-invalid={parsedKg?.kind === 'invalid'}
              />
            )}
          </Field>
        )}
        {!invalid && (
          <p className="text-sm text-stone-600">
            {t('inventory.difference')}:{' '}
            <span className="font-medium tabular-nums">
              {unchanged ? (
                t('inventory.noDifference')
              ) : (
                <>
                  {countDiff !== null && countDiff !== 0 && (
                    <span className={cx('mr-2', deltaTone(countDiff))}>{fmt.count(countDiff, true)}</span>
                  )}
                  {kgDiff !== null && kgDiff !== 0 && (
                    <span className={deltaTone(kgDiff)}>
                      {fmt.kg(formatScaled(kgDiff, KG_PLACES), true)}
                    </span>
                  )}
                </>
              )}
            </span>
          </p>
        )}
        <Field label={t('inventory.reason')} hint={t('inventory.reasonHint')}>
          {(id) => (
            <textarea
              id={id}
              rows={2}
              maxLength={INVENTORY_REASON_MAX_LENGTH}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="block w-full rounded-lg border-0 bg-white px-3 py-2 text-base text-stone-900 shadow-sm ring-1 ring-inset ring-stone-300 focus:ring-2 focus:ring-inset focus:ring-brand-500 sm:text-sm"
            />
          )}
        </Field>
      </div>
      {save.isError && (
        <Alert tone="error" className="mt-3">
          {errorMessage(save.error)}
        </Alert>
      )}
    </Sheet>
  )
}
