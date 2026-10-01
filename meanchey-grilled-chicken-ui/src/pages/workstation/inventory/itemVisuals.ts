/**
 * Item code → picture, short-name key and badge (wasted only), in one place. Pictures are plain files in
 * `src/assets/inventory/` (imported as URLs): replace a file to change a picture, no code change.
 *
 * Item codes come from the API catalog: `chicken`, `wings`, `thighs`, `packs_big`, `packs_small`,
 * `byproduct_processed.<code>`, `byproduct_packed.<code>`, `wasted.wings`, `wasted.thighs`,
 * `wasted.byproduct.<code>`. Processed and packed by-products share the by-product's picture;
 * wasted items reuse the base picture (drawn desaturated by the card). An unknown code (a future
 * by-product without a picture yet) gets `picture: null` → the generic box icon.
 */
import chicken from '@/assets/inventory/chicken.svg'
import gizzard from '@/assets/inventory/gizzard.svg'
import head from '@/assets/inventory/head.svg'
import heart from '@/assets/inventory/heart.svg'
import liver from '@/assets/inventory/liver.svg'
import pack2 from '@/assets/inventory/pack2.svg'
import pack4 from '@/assets/inventory/pack4.svg'
import thigh from '@/assets/inventory/thigh.svg'
import wing from '@/assets/inventory/wing.svg'
import type { InventoryItem } from '@/lib/types'

const PICTURES: Record<string, string> = {
  chicken,
  wings: wing,
  thighs: thigh,
  packs_big: pack4,
  packs_small: pack2,
  gizzard,
  liver,
  heart,
  head,
}

/** Short names (no "(processed)" / "(packed)": the Stock sub-tab says it) for these base codes. */
const SHORT_NAMES = new Set(Object.keys(PICTURES))

/** Only wasted items get a badge: the Stock sub-tab already says raw / processed / packed. */
export type ItemBadge = 'wasted'

export interface ItemVisual {
  /** The base item: `chicken`, `wings`, … or the by-product code (`liver`). */
  base: string
  picture: string | null
  badge: ItemBadge | null
  /** i18n key of the short name, or null → use the API's full name. */
  shortNameKey: string | null
  wasted: boolean
}

function baseOf(code: string): string {
  const parts = code.split('.')
  return parts[parts.length - 1]
}

export function itemVisual(item: Pick<InventoryItem, 'code' | 'section'>): ItemVisual {
  const base = baseOf(item.code)
  const wasted = item.section === 'wasted'
  const badge: ItemBadge | null = wasted ? 'wasted' : null
  return {
    base,
    picture: PICTURES[base] ?? null,
    badge,
    shortNameKey: SHORT_NAMES.has(base) ? `inventory.shortNames.${base}` : null,
    wasted,
  }
}
