/**
 * Item code → picture, short-name key and badge (wasted only), in one place. Pictures are plain files in
 * `src/assets/inventory/` (imported as URLs): replace a file to change a picture, no code change.
 *
 * Item codes come from the API catalog: `chicken`, `wings`, `thighs`, `packs_big`, `packs_small`,
 * `byproduct_processed.<code>`, `byproduct_packed.<code>`, `wasted.wings`, `wasted.thighs`,
 * `wasted.byproduct.<code>`. Processed and packed by-products share the by-product's picture;
 * wasted items reuse the base picture (drawn desaturated by the card). An unknown code (a future
 * by-product without a picture yet) gets `picture: null` → the generic box icon.
 *
 * Materials (`material_<id>`, created in the app): an uploaded icon (`iconUrl`, loaded by
 * materialIcons.ts) comes first, then the bundled picture of their `icon_key`
 * (`src/assets/inventory/materials/<key>.svg`, the default materials have one), then a generic
 * icon by unit — a scale for kg / g, a grid for m², a number tag for counted ones.
 *
 * Prepared items (section `prepared`): the satay sachets (`satay_sachet_2` / `_4`, a sachet
 * with a 2 / 4 badge) and the prepared twins of packaging materials (`<material>_prepared`,
 * carrying their material: the material's picture plus a small "Prepared" badge).
 */
import chicken from '@/assets/inventory/chicken.svg'
import gizzard from '@/assets/inventory/gizzard.svg'
import head from '@/assets/inventory/head.svg'
import heart from '@/assets/inventory/heart.svg'
import liver from '@/assets/inventory/liver.svg'
import pack2 from '@/assets/inventory/pack2.svg'
import pack4 from '@/assets/inventory/pack4.svg'
import sachet2 from '@/assets/inventory/sachet_2.svg'
import sachet4 from '@/assets/inventory/sachet_4.svg'
import thigh from '@/assets/inventory/thigh.svg'
import wing from '@/assets/inventory/wing.svg'
import marinade from '@/assets/inventory/materials/marinade.svg'
import satay from '@/assets/inventory/materials/satay.svg'
import skewer from '@/assets/inventory/materials/skewer.svg'
import sticker2 from '@/assets/inventory/materials/sticker_2.svg'
import sticker2M2 from '@/assets/inventory/materials/sticker_2_m2.svg'
import sticker4 from '@/assets/inventory/materials/sticker_4.svg'
import sticker4M2 from '@/assets/inventory/materials/sticker_4_m2.svg'
import string from '@/assets/inventory/materials/string.svg'
import vacuumBag from '@/assets/inventory/materials/vacuum_bag.svg'
import zipBag2 from '@/assets/inventory/materials/zip_bag_2.svg'
import zipBag4 from '@/assets/inventory/materials/zip_bag_4.svg'
import type { IconName } from '@/components/icons'
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
  satay_sachet_2: sachet2,
  satay_sachet_4: sachet4,
}

/** A material's `icon_key` (from the API) → bundled picture. An unknown key → the unit icon. */
const MATERIAL_PICTURES: Record<string, string> = {
  string,
  skewer,
  sticker_2: sticker2,
  sticker_4: sticker4,
  sticker_2_m2: sticker2M2,
  sticker_4_m2: sticker4M2,
  marinade,
  satay,
  zip_bag_2: zipBag2,
  zip_bag_4: zipBag4,
  vacuum_bag: vacuumBag,
}

/** The bundled picture of a material's `icon_key` (null: none, or a key this build doesn't know). */
export function materialPicture(iconKey: string | null | undefined): string | null {
  return (iconKey && MATERIAL_PICTURES[iconKey]) || null
}

/** Short names (no "(processed)" / "(packed)": the Stock sub-tab says it) for these base codes. */
const SHORT_NAMES = new Set(Object.keys(PICTURES))

/** Wasted items and prepared materials get a badge (the sub-tab says raw / processed / packed;
 * a prepared twin looks like its raw material otherwise). */
export type ItemBadge = 'wasted' | 'prepared'

export interface ItemVisual {
  /** The base item: `chicken`, `wings`, … or the by-product code (`liver`). */
  base: string
  /** The bundled picture (or null). */
  picture: string | null
  /** A material's uploaded icon (API path), drawn before `picture`; null for everything else. */
  iconUrl: string | null
  badge: ItemBadge | null
  /** i18n key of the short name, or null → use the API's full name. */
  shortNameKey: string | null
  wasted: boolean
  /** Without a picture: the icon to draw instead (materials by unit; else the box). */
  icon: IconName
}

function baseOf(code: string): string {
  const parts = code.split('.')
  return parts[parts.length - 1]
}

export function itemVisual(item: Pick<InventoryItem, 'code' | 'section'> & Partial<Pick<InventoryItem, 'material'>>): ItemVisual {
  if (item.material) {
    return {
      base: item.code,
      picture: materialPicture(item.material.icon_key),
      iconUrl: item.material.icon_url ?? null,
      badge: item.section === 'prepared' ? 'prepared' : null,
      shortNameKey: null,
      wasted: false,
      icon: item.material.unit === 'count' ? 'hash' : item.material.unit === 'm2' ? 'grid' : 'scale',
    }
  }
  const base = baseOf(item.code)
  const wasted = item.section === 'wasted'
  const badge: ItemBadge | null = wasted ? 'wasted' : null
  return {
    base,
    picture: PICTURES[base] ?? null,
    iconUrl: null,
    badge,
    shortNameKey: SHORT_NAMES.has(base) ? `inventory.shortNames.${base}` : null,
    wasted,
    icon: 'boxes',
  }
}
