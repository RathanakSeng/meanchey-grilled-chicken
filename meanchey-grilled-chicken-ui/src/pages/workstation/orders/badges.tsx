import { useTranslation } from 'react-i18next'
import { Badge, cx } from '@/components/ui'
import type { BoxColor, OrderStatus } from '@/lib/types'
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
