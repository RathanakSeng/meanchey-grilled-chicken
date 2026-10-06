import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import { Badge, cx } from '@/components/ui'
import type { BoxColor, CustomerBrief, OrderStatus } from '@/lib/types'
import { STATUS_TONES } from './api'

export function OrderStatusBadge({ status }: { status: OrderStatus }) {
  const { t } = useTranslation()
  return <Badge tone={STATUS_TONES[status]}>{t(`orders.status.${status}`)}</Badge>
}

/** A small white / black square, the colour of the box. */
export function BoxSwatch({ color, className }: { color: BoxColor; className?: string }) {
  return (
    <span
      aria-hidden
      className={cx(
        'inline-block h-3.5 w-3.5 shrink-0 rounded-[4px] ring-1 ring-inset',
        color === 'white' ? 'bg-white ring-stone-400' : 'bg-stone-900 ring-stone-900',
        className,
      )}
    />
  )
}

/** "▢ White box" / "■ Black box" (ប្រអប់ស / ប្រអប់ខ្មៅ). */
export function BoxColorLabel({ color, count }: { color: BoxColor; count?: number }) {
  const { t } = useTranslation()
  return (
    <span className="inline-flex items-center gap-1.5">
      <BoxSwatch color={color} />
      {count === undefined ? t(`orders.colors.${color}`) : t(`orders.colorBoxes.${color}`, { count })}
    </span>
  )
}

/** "▢ 2 · ■ 1" for list rows. */
export function BoxCounts({ white, black }: { white: number; black: number }) {
  const { t } = useTranslation()
  return (
    <span className="inline-flex items-center gap-2 tabular-nums" aria-label={t('orders.boxCountsLabel', { white, black })}>
      <span className="inline-flex items-center gap-1">
        <BoxSwatch color="white" />
        {white}
      </span>
      <span className="inline-flex items-center gap-1">
        <BoxSwatch color="black" />
        {black}
      </span>
    </span>
  )
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
