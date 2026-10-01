import type { ReactNode } from 'react'
import { Icon } from './icons'
import { cx } from './ui'

/**
 * A square item picture: an image file, or the generic box icon when there is none. `muted`
 * draws it desaturated (wasted items reuse the stock picture).
 */
export function ItemPicture({
  src,
  muted = false,
  className,
}: {
  src: string | null
  muted?: boolean
  className?: string
}) {
  return (
    <span
      className={cx(
        'flex shrink-0 items-center justify-center rounded-2xl bg-stone-50',
        muted && 'opacity-60 grayscale',
        className,
      )}
      aria-hidden
    >
      {src ? (
        <img src={src} alt="" className="h-4/5 w-4/5 object-contain" draggable={false} />
      ) : (
        <Icon name="boxes" className="h-1/2 w-1/2 text-stone-400" />
      )}
    </span>
  )
}

export type ItemCardBadgeTone = 'wasted'

const BADGE_TONES: Record<ItemCardBadgeTone, string> = {
  wasted: 'bg-red-50 text-red-700 ring-red-200',
}

/**
 * One inventory item as a product-style card: picture, optional corner badge, name (2 lines),
 * a big number, an optional second line (e.g. the kg of a counted item), the last change and an
 * optional full-width action. The whole card (except the action) is a button that opens the
 * item; without an action a spacer keeps every card in a row the same height.
 */
export function InventoryItemCard({
  picture,
  mutedPicture = false,
  badge,
  name,
  amount,
  secondary,
  updated,
  zero = false,
  ariaLabel,
  onOpen,
  action,
}: {
  picture: string | null
  mutedPicture?: boolean
  badge?: { tone: ItemCardBadgeTone; label: string }
  name: string
  amount: string
  secondary?: ReactNode
  updated: string
  /** Zero balance: dimmed, still clickable. */
  zero?: boolean
  ariaLabel: string
  onOpen(): void
  action?: ReactNode
}) {
  return (
    <div
      className={cx(
        'relative flex h-full flex-col rounded-2xl bg-white shadow-sm ring-1 ring-stone-200 transition',
        'hover:ring-brand-300',
      )}
    >
      <button
        type="button"
        onClick={onOpen}
        aria-label={ariaLabel}
        className="flex flex-1 flex-col items-center rounded-2xl px-3 pb-2 pt-4 text-center focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
      >
        {badge && (
          <span
            className={cx(
              'absolute right-2 top-2 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset',
              BADGE_TONES[badge.tone],
            )}
          >
            {badge.label}
          </span>
        )}
        <ItemPicture
          src={picture}
          muted={mutedPicture}
          className={cx('h-[72px] w-[72px] sm:h-[88px] sm:w-[88px]', zero && 'opacity-50')}
        />
        <span className="mt-2 line-clamp-2 min-h-[2.5rem] text-sm font-medium leading-5 text-stone-800">
          {name}
        </span>
        <span
          className={cx(
            'mt-1 text-2xl font-semibold tabular-nums leading-tight',
            zero ? 'text-stone-300' : 'text-stone-900',
          )}
        >
          {amount}
        </span>
        <span className={cx('min-h-[1.25rem] text-xs tabular-nums', zero ? 'text-stone-300' : 'text-stone-500')}>
          {secondary}
        </span>
        <span className="mt-auto pt-1 text-[11px] text-stone-400">{updated}</span>
      </button>
      <div className="px-3 pb-3">{action ?? <span className="block h-9" aria-hidden />}</div>
    </div>
  )
}

/** Placeholder card while the inventory loads (same size as a real one). */
export function InventoryCardSkeleton() {
  return (
    <div className="flex h-full animate-pulse flex-col items-center rounded-2xl bg-white px-3 pb-3 pt-4 shadow-sm ring-1 ring-stone-200">
      <span className="h-[72px] w-[72px] rounded-2xl bg-stone-100 sm:h-[88px] sm:w-[88px]" />
      <span className="mt-3 h-4 w-20 rounded bg-stone-100" />
      <span className="mt-2 h-7 w-12 rounded bg-stone-200" />
      <span className="mt-2 h-3 w-16 rounded bg-stone-100" />
      <span className="mt-3 h-9 w-full rounded-lg bg-stone-100" />
    </div>
  )
}
