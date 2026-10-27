import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { ItemPicture } from '@/components/InventoryItemCard'
import { Icon } from '@/components/icons'
import { Sheet } from '@/components/Sheet'
import { Alert, Button, Field, Input, Spinner, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { getError, useErrorMessage } from '@/lib/errors'
import { useLocalized } from '@/lib/format'
import { paths } from '@/lib/paths'
import {
  UNIT_DECIMALS,
  amountIn,
  parseQuantity,
  scaledOfAmount,
  toApiQuantity,
  useQuantityFormat,
  type QuantityUnit,
} from '@/lib/quantity'
import {
  CLEAR_REASON_MAX_LENGTH,
  type ClearImpact,
  type ClearImpactType,
  type ClearPreview,
  type InventoryClear,
  type InventoryItem,
} from '@/lib/types'
import { useDebounced } from '@/lib/useDebounced'
import { invalidateInventory } from './api'
import { useItemPicture } from './materialIcons'
import { useItemDisplay } from './useItemDisplay'

const IMPACT_TYPES: ClearImpactType[] = ['order', 'production', 'plan', 'preparation', 'reopen']

const textareaClass =
  'block w-full rounded-lg border-0 bg-white px-3 py-2 text-base text-stone-900 shadow-sm ring-1 ring-inset ring-stone-300 focus:ring-2 focus:ring-inset focus:ring-brand-500 sm:text-sm'

/** The unit a clear line is entered in: the count for counted items, else the item's one unit. */
export function clearUnit(item: InventoryItem): QuantityUnit {
  if (item.tracks_count) return 'count'
  if (item.tracks_kg) return 'kg'
  return item.tracks_g ? 'g' : 'm2'
}

/** Production items in Processed / Packed move to Wasted; everything else is removed. */
export function movesToWasted(item: InventoryItem): boolean {
  return item.origin === 'production' && (item.group === 'processed' || item.group === 'packed')
}

/** Where an impact's code links to. */
export function impactLink(impact: ClearImpact): string {
  switch (impact.type) {
    case 'order':
      return paths.order(impact.id)
    case 'plan':
      return paths.productionPlan(impact.id)
    case 'preparation':
      return paths.preparation(impact.id)
    case 'production':
      return paths.productionBatch(impact.id, impact.step ?? undefined)
    case 'reopen':
      return impact.message_key === 'reopen_preparation_blocked'
        ? paths.preparation(impact.id)
        : paths.productionBatch(impact.id, impact.step ?? undefined)
  }
}

/** "Affects 2 orders, 1 production batch" parts, per type (distinct records). */
export function useImpactSummary() {
  const { t } = useTranslation()
  return (impacts: ClearImpact[]): string =>
    IMPACT_TYPES.map((type) => {
      const count = new Set(impacts.filter((i) => i.type === type).map((i) => i.id)).size
      return count ? t(`inventory.clear.affects.${type}`, { count }) : null
    })
      .filter(Boolean)
      .join(', ')
}

/**
 * The impacts grouped (Orders · Production · Plans · Preparations · Reopen), each with the record's
 * code (linking to it) and what it leaves short. Also used by the clear record.
 */
export function ImpactList({ impacts }: { impacts: ClearImpact[] }) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const format = useQuantityFormat()
  return (
    <div className="space-y-3">
      {IMPACT_TYPES.map((type) => {
        const rows = impacts.filter((i) => i.type === type)
        if (rows.length === 0) return null
        return (
          <div key={type}>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-stone-500">
              {t(`inventory.clear.groups.${type}`)}
            </h4>
            <ul className="space-y-1">
              {rows.map((i) => (
                <li key={`${i.id}-${i.item_code}`} className="text-sm text-stone-700">
                  <Link to={impactLink(i)} className="font-medium tabular-nums text-brand-700 hover:underline">
                    {i.code}
                  </Link>{' '}
                  {t(`inventory.clear.impact.${i.message_key}`, {
                    item: localized(i),
                    step: i.step ?? '',
                    needed: format(i.needed, i.unit),
                    available: format(i.available_after, i.unit),
                  })}
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </div>
  )
}

/**
 * Review sheet of a clear: per chosen item its picture, name, stock, the amount to clear (empty by
 * default, **All** fills the whole stock), the live "120 → 100" and where it goes (→ Wasted or
 * Removed); a required reason; the impacts from the dry run (refreshed as amounts change) with a
 * required acknowledgement; **Confirm clear**.
 */
export function ClearSheet({
  items,
  onRemove,
  onClose,
  onDone,
}: {
  items: InventoryItem[]
  onRemove(code: string): void
  onClose(): void
  onDone(clear: InventoryClear): void
}) {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const queryClient = useQueryClient()
  const summary = useImpactSummary()
  const [amounts, setAmounts] = useState<Record<string, string>>({})
  const [reason, setReason] = useState('')
  const [acknowledged, setAcknowledged] = useState(false)

  const rows = items.map((item) => {
    const unit = clearUnit(item)
    const current = scaledOfAmount(amountIn(item, unit), unit)
    const parsed = parseQuantity(amounts[item.code] ?? '', unit)
    const tooMuch = parsed.kind === 'ok' && parsed.scaled > current
    return { item, unit, current, parsed, tooMuch, valid: parsed.kind === 'ok' && !tooMuch }
  })
  const lines = rows
    .filter((r) => r.valid && r.parsed.kind === 'ok')
    .map((r) => ({
      item_code: r.item.code,
      quantity: String(toApiQuantity(r.parsed.kind === 'ok' ? r.parsed.scaled : 0, r.unit)),
    }))
  const allValid = rows.every((r) => r.valid)
  const linesKey = JSON.stringify(lines)
  const debouncedKey = useDebounced(linesKey, 400)
  const debouncedLines = useMemo(() => JSON.parse(debouncedKey) as typeof lines, [debouncedKey])

  const preview = useQuery({
    queryKey: ['inventory-clear-preview', debouncedLines],
    queryFn: async () => (await api.post<ClearPreview>('/inventory/clears/preview', { lines: debouncedLines })).data,
    enabled: debouncedLines.length > 0,
    placeholderData: keepPreviousData,
  })
  const fresh = allValid && debouncedKey === linesKey && preview.data !== undefined && !preview.isPlaceholderData
  const impacts = fresh ? preview.data.impacts : []
  // The impacts changed: acknowledge them again.
  const impactsKey = JSON.stringify(impacts)
  useEffect(() => setAcknowledged(false), [impactsKey])

  const save = useMutation({
    mutationFn: async () =>
      (
        await api.post<InventoryClear>('/inventory/clears', {
          lines,
          reason: reason.trim(),
          acknowledge_impacts: impacts.length > 0,
        })
      ).data,
    onSuccess: (clear) => {
      invalidateInventory(queryClient)
      onDone(clear)
    },
    onError: (error) => {
      // Stock changed meanwhile: show the new impacts.
      if (getError(error)?.code === 'INVENTORY_CLEAR_UNACKNOWLEDGED') {
        void queryClient.invalidateQueries({ queryKey: ['inventory-clear-preview'] })
      }
    },
  })

  const ready =
    lines.length === items.length &&
    allValid &&
    fresh &&
    reason.trim().length > 0 &&
    (impacts.length === 0 || acknowledged)

  return (
    <Sheet
      open
      title={t('inventory.clear.title')}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose} disabled={save.isPending}>
            {t('common.cancel')}
          </Button>
          <Button variant="danger" loading={save.isPending} disabled={!ready} onClick={() => save.mutate()}>
            {t('inventory.clear.confirm')}
          </Button>
        </div>
      }
    >
      <p className="mb-4 text-sm text-stone-600">{t('inventory.clear.intro')}</p>
      <ul className="divide-y divide-stone-100 rounded-xl ring-1 ring-stone-200">
        {rows.map((row) => (
          <ClearRow
            key={row.item.code}
            row={row}
            kg={fresh ? (preview.data.lines.find((l) => l.item_code === row.item.code) ?? null) : null}
            value={amounts[row.item.code] ?? ''}
            onChange={(value) => setAmounts((prev) => ({ ...prev, [row.item.code]: value }))}
            onRemove={() => onRemove(row.item.code)}
          />
        ))}
      </ul>

      <Field label={t('inventory.clear.reason')} className="mt-4" hint={t('inventory.clear.reasonHint')}>
        {(id) => (
          <textarea
            id={id}
            rows={2}
            maxLength={CLEAR_REASON_MAX_LENGTH}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className={textareaClass}
          />
        )}
      </Field>

      <div className="mt-4" aria-live="polite">
        {preview.isFetching && lines.length > 0 && (
          <p className="flex items-center gap-2 text-sm text-stone-500">
            <Spinner className="h-4 w-4" /> {t('inventory.clear.checking')}
          </p>
        )}
        {preview.isError && !preview.isFetching && <Alert tone="error">{errorMessage(preview.error)}</Alert>}
        {impacts.length > 0 && (
          <div className="rounded-xl bg-red-50 p-3 ring-1 ring-inset ring-red-200">
            <p className="mb-2 flex items-start gap-2 text-sm font-semibold text-red-800">
              <Icon name="alert" width={18} height={18} className="mt-0.5 shrink-0" />
              {t('inventory.clear.affectsSummary', { list: summary(impacts) })}
            </p>
            <ImpactList impacts={impacts} />
            <label className="mt-3 flex items-start gap-2 text-sm font-medium text-stone-800">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(e) => setAcknowledged(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-stone-300 text-red-600 focus:ring-red-500"
              />
              {t('inventory.clear.acknowledge')}
            </label>
          </div>
        )}
        {fresh && impacts.length === 0 && (
          <p className="text-sm text-stone-500">{t('inventory.clear.noImpacts')}</p>
        )}
      </div>

      <p className="mt-4 text-xs text-stone-500">{t('inventory.clear.noUndo')}</p>
      {save.isError && (
        <Alert tone="error" className="mt-3">
          {errorMessage(save.error)}
        </Alert>
      )}
    </Sheet>
  )
}

function ClearRow({
  row,
  kg,
  value,
  onChange,
  onRemove,
}: {
  row: {
    item: InventoryItem
    unit: QuantityUnit
    current: number
    parsed: ReturnType<typeof parseQuantity>
    tooMuch: boolean
  }
  /** The dry run's line (the kg a counted item takes). */
  kg: { kg: string | null; kg_estimated: boolean } | null
  value: string
  onChange(value: string): void
  onRemove(): void
}) {
  const { t } = useTranslation()
  const format = useQuantityFormat()
  const display = useItemDisplay()
  const { item, unit, current, parsed, tooMuch } = row
  const d = display(item)
  const picture = useItemPicture(d.visual)
  const places = UNIT_DECIMALS[unit]
  const after = parsed.kind === 'ok' ? current - parsed.scaled : null
  const name = d.visual.wasted && d.badgeLabel ? `${d.badgeLabel}: ${d.fullName}` : d.fullName

  return (
    <li className="flex gap-3 p-3">
      <ItemPicture src={picture} icon={d.visual.icon} muted={d.visual.wasted} className="h-12 w-12" />
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-2">
          <p className="min-w-0 flex-1 font-medium text-stone-900">{name}</p>
          <button
            type="button"
            onClick={onRemove}
            aria-label={t('inventory.clear.removeLine', { name })}
            className="-m-1 rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700"
          >
            <Icon name="close" width={16} height={16} />
          </button>
        </div>
        <p className="text-xs text-stone-500">
          {t('inventory.clear.inStock', { amount: format(toApiQuantity(current, unit), unit) })}
          {' · '}
          <span className={movesToWasted(item) ? 'text-red-700' : undefined}>
            {t(movesToWasted(item) ? 'inventory.clear.toWasted' : 'inventory.clear.removed')}
          </span>
        </p>
        <div className="mt-2 flex items-center gap-2">
          <Input
            inputMode={places === 0 ? 'numeric' : 'decimal'}
            autoComplete="off"
            value={value}
            placeholder="0"
            onChange={(e) => onChange(e.target.value)}
            aria-label={t('inventory.clear.amount', { name, unit: t(`materials.units.${unit}`) })}
            aria-invalid={parsed.kind === 'invalid' || tooMuch ? true : undefined}
            className="h-11 w-32 tabular-nums sm:h-9"
          />
          <Button
            variant="secondary"
            className="whitespace-nowrap"
            onClick={() => onChange(String(toApiQuantity(current, unit)))}
          >
            {t('inventory.clear.all')}
          </Button>
        </div>
        <p
          className={cx(
            'mt-1 text-sm tabular-nums',
            parsed.kind === 'invalid' || tooMuch ? 'font-medium text-red-700' : 'text-stone-700',
          )}
        >
          {parsed.kind === 'invalid'
            ? t(`materials.invalid.${unit}`)
            : tooMuch
              ? t('inventory.clear.tooMuch', { amount: format(toApiQuantity(current, unit), unit) })
              : after !== null
                ? `${format(toApiQuantity(current, unit), unit)} → ${format(toApiQuantity(after, unit), unit)}`
                : t('inventory.clear.enterAmount')}
          {kg?.kg && after !== null && !tooMuch && (
            <span className="ml-2 text-xs text-stone-500" title={kg.kg_estimated ? t('inventory.estimatedHint') : undefined}>
              ({kg.kg_estimated ? '≈ ' : ''}
              {format(kg.kg, 'kg')})
            </span>
          )}
        </p>
      </div>
    </li>
  )
}
