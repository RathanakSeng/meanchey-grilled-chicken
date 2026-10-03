import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Sheet } from '@/components/Sheet'
import { Alert, Button, Field, Input, cx } from '@/components/ui'
import { useLocalized } from '@/lib/format'
import { ORDER_REASON_MAX_LENGTH, type Order, type OrderUnit } from '@/lib/types'
import { amountOf, parseAmount, toApi, useAmountFormat } from './api'

const textareaClass =
  'block w-full rounded-lg border-0 bg-white px-3 py-2 text-base text-stone-900 shadow-sm ring-1 ring-inset ring-stone-300 placeholder:text-stone-400 focus:ring-2 focus:ring-inset focus:ring-brand-500 sm:text-sm'

function AmountInput({
  unit,
  value,
  onChange,
  label,
  invalid,
}: {
  unit: OrderUnit
  value: string
  onChange(value: string): void
  label: string
  invalid?: boolean
}) {
  const { t } = useTranslation()
  return (
    <div className="relative">
      <Input
        aria-label={label}
        aria-invalid={invalid || undefined}
        inputMode={unit === 'kg' ? 'decimal' : 'numeric'}
        placeholder={unit === 'kg' ? '0.000' : '0'}
        className={cx('h-11 text-right tabular-nums sm:h-10', unit === 'kg' && 'pr-9', invalid && 'ring-red-400')}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {unit === 'kg' && (
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-stone-500">
          {t('orders.kgUnit')}
        </span>
      )}
    </div>
  )
}

function Footer({
  onCancel,
  onSubmit,
  label,
  busy,
  disabled,
}: {
  onCancel(): void
  onSubmit(): void
  label: string
  busy: boolean
  disabled: boolean
}) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
      <Button variant="secondary" onClick={onCancel} disabled={busy}>
        {t('common.cancel')}
      </Button>
      <Button onClick={onSubmit} loading={busy} disabled={disabled}>
        {label}
      </Button>
    </div>
  )
}

export interface DeliveredBody {
  outcome: 'accepted' | 'returned'
  reason?: string
  items?: { item_code: string; count?: number; kg?: string }[]
}

/**
 * Mark delivered: **Everything accepted**, or **Some items returned** with a quantity per item
 * (at most what was delivered, shown next to it) and a required reason.
 */
export function DeliveredSheet({
  order,
  open,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  order: Order
  open: boolean
  busy: boolean
  error: string | null
  onClose(): void
  onSubmit(body: DeliveredBody): void
}) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const format = useAmountFormat()
  const [outcome, setOutcome] = useState<'accepted' | 'returned'>('accepted')
  const [reason, setReason] = useState('')
  const [values, setValues] = useState<Record<string, string>>({})

  const items = order.summary.total.items
  const rows = items.map((item) => {
    const raw = values[item.item_code] ?? ''
    const amount = raw.trim() ? parseAmount(item.unit, raw) : 0
    const max = amountOf(item)
    const invalid = amount === null || amount > max
    return { item, raw, amount: amount ?? 0, max, invalid }
  })
  const returned = rows.filter((r) => !r.invalid && r.amount > 0)
  const valid =
    outcome === 'accepted' || (reason.trim() !== '' && returned.length > 0 && rows.every((r) => !r.invalid))

  const submit = () =>
    onSubmit(
      outcome === 'accepted'
        ? { outcome }
        : {
            outcome,
            reason: reason.trim(),
            items: returned.map((r) => ({ item_code: r.item.item_code, ...toApi(r.item.unit, r.amount) })),
          },
    )

  return (
    <Sheet
      open={open}
      title={t('orders.markDelivered')}
      onClose={onClose}
      busy={busy}
      footer={
        <Footer
          onCancel={onClose}
          onSubmit={submit}
          label={t('orders.confirmDelivered')}
          busy={busy}
          disabled={!valid}
        />
      }
    >
      <div role="radiogroup" aria-label={t('orders.markDelivered')} className="mb-4 grid gap-2">
        {(['accepted', 'returned'] as const).map((value) => (
          <label
            key={value}
            className={cx(
              'flex cursor-pointer items-start gap-3 rounded-xl p-3 ring-1 ring-inset',
              outcome === value ? 'bg-brand-50 ring-2 ring-brand-500' : 'bg-white ring-stone-300',
            )}
          >
            <input
              type="radio"
              name="outcome"
              className="mt-1"
              checked={outcome === value}
              onChange={() => setOutcome(value)}
            />
            <span>
              <span className="block font-medium text-stone-900">{t(`orders.outcome.${value}`)}</span>
              <span className="block text-sm text-stone-500">{t(`orders.outcomeHint.${value}`)}</span>
            </span>
          </label>
        ))}
      </div>

      {outcome === 'returned' && (
        <div className="space-y-3">
          <p className="text-sm text-stone-600">{t('orders.returnedHint')}</p>
          <ul className="space-y-2">
            {rows.map(({ item, raw, max, invalid }) => (
              <li key={item.item_code} className="grid grid-cols-[1fr_8rem] items-center gap-3">
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-stone-900">{localized(item)}</span>
                  <span className="block text-xs text-stone-500">
                    {t('orders.deliveredAmount', { amount: format(item.unit, max) })}
                  </span>
                </span>
                <AmountInput
                  unit={item.unit}
                  label={t('orders.returnedOf', { name: localized(item) })}
                  value={raw}
                  invalid={invalid}
                  onChange={(v) => setValues({ ...values, [item.item_code]: v })}
                />
              </li>
            ))}
          </ul>
          <Field label={t('orders.returnReason')}>
            {(id) => (
              <textarea
                id={id}
                rows={3}
                maxLength={ORDER_REASON_MAX_LENGTH}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder={t('orders.returnReasonPlaceholder')}
                className={textareaClass}
              />
            )}
          </Field>
        </div>
      )}
      {error && (
        <Alert tone="error" className="mt-3">
          {error}
        </Alert>
      )}
    </Sheet>
  )
}

export interface ReviewBody {
  items: {
    item_code: string
    to_stock_count?: number
    to_stock_kg?: string
    to_wasted_count?: number
    to_wasted_kg?: string
  }[]
}

/**
 * Review return: per returned item, how much goes **Back to stock** and how much is **Wasted**;
 * the two must add up to what came back. "All to stock" / "All wasted" fill every item.
 */
export function ReviewSheet({
  order,
  open,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  order: Order
  open: boolean
  busy: boolean
  error: string | null
  onClose(): void
  onSubmit(body: ReviewBody): void
}) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const format = useAmountFormat()
  const [values, setValues] = useState<Record<string, { stock: string; wasted: string }>>({})

  const show = (unit: OrderUnit, amount: number) =>
    unit === 'count' ? String(amount) : (amount / 1000).toFixed(3)
  const fill = (target: 'stock' | 'wasted') =>
    setValues(
      Object.fromEntries(
        order.returns.map((r) => {
          const all = show(r.unit, amountOf({ count: r.returned_count, kg: r.returned_kg }))
          const zero = r.unit === 'count' ? '0' : '0.000'
          return [r.item_code, target === 'stock' ? { stock: all, wasted: zero } : { stock: zero, wasted: all }]
        }),
      ),
    )

  const rows = order.returns.map((r) => {
    const v = values[r.item_code] ?? { stock: '', wasted: '' }
    const returned = amountOf({ count: r.returned_count, kg: r.returned_kg })
    const stock = v.stock.trim() ? parseAmount(r.unit, v.stock) : 0
    const wasted = v.wasted.trim() ? parseAmount(r.unit, v.wasted) : 0
    const matches = stock !== null && wasted !== null && stock + wasted === returned
    return { r, v, returned, stock: stock ?? 0, wasted: wasted ?? 0, matches, touched: Boolean(v.stock || v.wasted) }
  })
  const valid = rows.length > 0 && rows.every((row) => row.matches)
  const set = (code: string, field: 'stock' | 'wasted', value: string) =>
    setValues({ ...values, [code]: { ...(values[code] ?? { stock: '', wasted: '' }), [field]: value } })

  const submit = () =>
    onSubmit({
      items: rows.map(({ r, stock, wasted }) =>
        r.unit === 'count'
          ? { item_code: r.item_code, to_stock_count: stock, to_wasted_count: wasted }
          : {
              item_code: r.item_code,
              to_stock_kg: (stock / 1000).toFixed(3),
              to_wasted_kg: (wasted / 1000).toFixed(3),
            },
      ),
    })

  return (
    <Sheet
      open={open}
      title={t('orders.reviewReturn')}
      onClose={onClose}
      busy={busy}
      footer={
        <Footer onCancel={onClose} onSubmit={submit} label={t('orders.confirmReview')} busy={busy} disabled={!valid} />
      }
    >
      {order.return_reason && (
        <p className="mb-3 rounded-lg bg-stone-50 p-2 text-sm text-stone-700">
          {t('orders.reasonQuoted', { reason: order.return_reason })}
        </p>
      )}
      <div className="mb-3 flex flex-wrap gap-2">
        <Button variant="secondary" className="px-3 py-1.5" onClick={() => fill('stock')}>
          {t('orders.allToStock')}
        </Button>
        <Button variant="secondary" className="px-3 py-1.5" onClick={() => fill('wasted')}>
          {t('orders.allWasted')}
        </Button>
      </div>
      <ul className="space-y-3">
        {rows.map(({ r, v, returned, stock, wasted, matches, touched }) => (
          <li key={r.item_code} className="rounded-xl p-3 ring-1 ring-stone-200">
            <p className="mb-2 flex items-baseline justify-between gap-2 text-sm">
              <span className="font-medium text-stone-900">{localized(r)}</span>
              <span className="tabular-nums text-stone-600">
                {t('orders.returnedAmount', { amount: format(r.unit, returned) })}
              </span>
            </p>
            <div className="grid grid-cols-2 gap-2">
              <Field label={t('orders.backToStock')}>
                {() => (
                  <AmountInput
                    unit={r.unit}
                    label={`${localized(r)} — ${t('orders.backToStock')}`}
                    value={v.stock}
                    invalid={touched && !matches}
                    onChange={(value) => set(r.item_code, 'stock', value)}
                  />
                )}
              </Field>
              <Field label={t('orders.wasted')}>
                {() => (
                  <AmountInput
                    unit={r.unit}
                    label={`${localized(r)} — ${t('orders.wasted')}`}
                    value={v.wasted}
                    invalid={touched && !matches}
                    onChange={(value) => set(r.item_code, 'wasted', value)}
                  />
                )}
              </Field>
            </div>
            {touched && !matches && (
              <p className="mt-1 text-xs text-red-700">
                {t('orders.mustAddUp', {
                  sum: format(r.unit, stock + wasted),
                  returned: format(r.unit, returned),
                })}
              </p>
            )}
          </li>
        ))}
      </ul>
      {error && (
        <Alert tone="error" className="mt-3">
          {error}
        </Alert>
      )}
    </Sheet>
  )
}
