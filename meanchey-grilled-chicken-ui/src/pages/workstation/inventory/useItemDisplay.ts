import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocalized } from '@/lib/format'
import type { InventoryItem } from '@/lib/types'
import { useStockFormat } from './api'
import { itemVisual, type ItemVisual } from './itemVisuals'

export interface ItemDisplay {
  visual: ItemVisual
  /** Without "(processed)" / "(packed)" (the sub-tab says it); the API name for unknown items. */
  shortName: string
  /** The API's full name, e.g. "Liver (processed)" (History, sheet title). */
  fullName: string
  badgeLabel: string | null
  /** The big number: the count for counted items, else the kg with its unit. */
  amount: string
  /** The kg under the count, for items with both units ("≈" when estimated). */
  secondary: string | null
  zero: boolean
}

/** How an inventory item reads on its card and in its sheet. */
export function useItemDisplay() {
  const { t } = useTranslation()
  const localized = useLocalized()
  const { count: formatCount, kg: formatKg } = useStockFormat()
  return useCallback(
    (item: InventoryItem): ItemDisplay => {
      const visual = itemVisual(item)
      const fullName = localized(item)
      const counted = item.count !== null
      const kg = item.kg !== null ? formatKg(item.kg) : null
      return {
        visual,
        fullName,
        shortName: visual.shortNameKey ? t(visual.shortNameKey, { defaultValue: fullName }) : fullName,
        badgeLabel: visual.badge ? t(`inventory.badges.${visual.badge}`) : null,
        amount: counted ? formatCount(item.count ?? 0) : (kg ?? '—'),
        secondary: counted && kg !== null ? `${item.kg_estimated ? '≈ ' : ''}${kg}` : null,
        zero: (item.count ?? 0) === 0 && Number(item.kg ?? 0) === 0,
      }
    },
    [t, localized, formatCount, formatKg],
  )
}
