import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import { Badge, cx } from '@/components/ui'
import { BOX_COLORS, type BoxColor, type CustomerBrief, type OrderListItem, type OrderStatus } from '@/lib/types'
import { STATUS_TONES } from './api'

export function OrderStatusBadge({ status }: { status: OrderStatus }) {
  const { t } = useTranslation()
  return <Badge tone={STATUS_TONES[status]}>{t(`orders.status.${status}`)}</Badge>
}

const SWATCHES: Record<BoxColor, string> = {
  white: 'bg-white ring-1 ring-inset ring-stone-400',
  black: 'bg-stone-900 ring-1 ring-inset ring-stone-900',
  // Bags: a dashed outline (plastic), half filled (delivery), like the printed delivery note.
  plastic_bag: 'border border-dashed border-stone-500 bg-white',
  delivery_bag: 'bg-[linear-gradient(135deg,theme(colors.stone.900)_50%,white_50%)] ring-1 ring-inset ring-stone-900',
}

/** A small square marking the container: white / black box, plastic / delivery bag. */
export function BoxSwatch({ color, className }: { color: BoxColor; className?: string }) {
  return <span aria-hidden className={cx('inline-block h-3.5 w-3.5 shrink-0 rounded-[4px]', SWATCHES[color], className)} />
}

/** "▢ White box" / "■ Black box" / "Plastic bag" / "Delivery bag" (ប្រអប់ស / ប្រអប់ខ្មៅ / …). */
export function BoxColorLabel({ color, count }: { color: BoxColor; count?: number }) {
  const { t } = useTranslation()
  return (
    <span className="inline-flex items-center gap-1.5">
      <BoxSwatch color={color} />
      {count === undefined ? t(`orders.colors.${color}`) : t(`orders.colorBoxes.${color}`, { count })}
    </span>
  )
}

/** "2 white boxes, 1 plastic bag" (containers without boxes left out). */
export function boxCountsText(t: TFunction, counts: Partial<Record<BoxColor, number>>) {
  return BOX_COLORS.filter((c) => (counts[c] ?? 0) > 0)
    .map((c) => t(`orders.colorCount.${c}`, { count: counts[c] }))
    .join(', ')
}

/** "▢ 2 · ■ 1" for list rows; the bags only when the order has some. */
export function BoxCounts({ counts }: { counts: Record<BoxColor, number> }) {
  const { t } = useTranslation()
  const shown = BOX_COLORS.filter((c) => c === 'white' || c === 'black' || counts[c] > 0)
  return (
    <span className="inline-flex items-center gap-2 tabular-nums" aria-label={boxCountsText(t, counts)}>
      {shown.map((c) => (
        <span key={c} className="inline-flex items-center gap-1">
          <BoxSwatch color={c} />
          {counts[c]}
        </span>
      ))}
    </span>
  )
}

/** "🧺 2 not returned": boxes recorded as not returned at delivery (nothing when none). */
export function ContainersOutstandingBadge({ count }: { count: number }) {
  const { t } = useTranslation()
  if (count <= 0) return null
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-inset ring-amber-200">
      <span aria-hidden>🧺</span>
      {t('orders.containers.notReturnedCount', { count })}
    </span>
  )
}

/** The list row's box counts per container. */
export function listBoxCounts(item: OrderListItem): Record<BoxColor, number> {
  return {
    white: item.white_boxes,
    black: item.black_boxes,
    plastic_bag: item.plastic_bag_boxes,
    delivery_bag: item.delivery_bag_boxes,
  }
}

/** The order's customer as one line of text: the name, or "Direct order · 012 345 678". */
export function customerText(t: TFunction, customer: Pick<CustomerBrief, 'name' | 'phone_display'>) {
  return customer.name ?? t('orders.directOrderWithPhone', { phone: customer.phone_display ?? '—' })
}

/** `tel:` link of a readable phone ("012 345 678" → "tel:012345678"). */
export function telHref(phone: string) {
  return `tel:${phone.replace(/[^\d+]/g, '')}`
}

export function DirectOrderBadge() {
  const { t } = useTranslation()
  return <Badge tone="blue">{t('orders.directOrder')}</Badge>
}

/**
 * The customer in lists: the saved customer's name, or the Direct order badge with the phone.
 * `withPhone` also shows a saved customer's phone.
 */
export function OrderCustomerName({ customer, withPhone = false }: { customer: CustomerBrief; withPhone?: boolean }) {
  if (customer.type === 'direct' || !customer.name) {
    return (
      <span className="inline-flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5">
        <DirectOrderBadge />
        {customer.phone_display && <span className="tabular-nums">{customer.phone_display}</span>}
      </span>
    )
  }
  return (
    <span className="min-w-0">
      {customer.name}
      {withPhone && customer.phone_display && (
        <span className="ml-1.5 tabular-nums text-stone-500">{customer.phone_display}</span>
      )}
    </span>
  )
}
