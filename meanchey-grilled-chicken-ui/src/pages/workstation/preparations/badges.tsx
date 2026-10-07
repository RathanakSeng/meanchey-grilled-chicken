import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { ItemPicture } from '@/components/InventoryItemCard'
import { Badge, cx } from '@/components/ui'
import { useLocalized } from '@/lib/format'
import { useQuantityFormat } from '@/lib/quantity'
import type { PreparationItem, PreparationMaterial, PreparationStatus, PreparationType } from '@/lib/types'
import { itemVisual } from '@/pages/workstation/inventory/itemVisuals'
import { useItemPicture } from '@/pages/workstation/inventory/materialIcons'

const STATUS_TONES = { draft: 'amber', finished: 'green', cancelled: 'neutral' } as const
const TYPE_TONES = { satay_sachet: 'brand', packaging_material: 'blue' } as const

export function PreparationStatusBadge({ status }: { status: PreparationStatus }) {
  const { t } = useTranslation()
  return <Badge tone={STATUS_TONES[status]}>{t(`preparations.status.${status}`)}</Badge>
}

export function PreparationTypeBadge({ type }: { type: PreparationType }) {
  const { t } = useTranslation()
  return <Badge tone={TYPE_TONES[type]}>{t(`preparations.types.${type}.short`)}</Badge>
}

/** "40 × Satay sachets (2-piece packs), 25 × …" / "Skewer 2.000 kg, String 0.500 kg". */
export function useOutputsText() {
  const { t } = useTranslation()
  const localized = useLocalized()
  const format = useQuantityFormat()
  return useCallback(
    (outputs: PreparationItem[]) =>
      outputs.length === 0
        ? t('preparations.nothingYet')
        : outputs
            .map((o) =>
              o.unit === 'count'
                ? t('preparations.countOf', { n: Number(o.quantity), name: localized(o) })
                : `${localized(o)} ${format(o.quantity, o.unit)}`,
            )
            .join(', '),
    [t, localized, format],
  )
}

/** A material's picture: uploaded icon, bundled picture (`icon_key`), else the unit icon. */
export function MaterialThumb({
  material,
  className,
}: {
  material: Pick<PreparationMaterial, 'id' | 'item_code' | 'unit' | 'icon_key' | 'icon_url'>
  className?: string
}) {
  const visual = itemVisual({
    code: material.item_code,
    section: 'stock',
    material: {
      id: material.id,
      unit: material.unit,
      system_code: null,
      archived: false,
      icon_key: material.icon_key,
      icon_url: material.icon_url,
    },
  })
  const picture = useItemPicture(visual)
  return <ItemPicture src={picture} icon={visual.icon} className={cx('h-10 w-10 shrink-0', className)} />
}

/** A catalog item's picture (the satay sachets), by item code. */
export function ItemThumb({ code, className }: { code: string; className?: string }) {
  const visual = itemVisual({ code, section: 'prepared' })
  const picture = useItemPicture(visual)
  return <ItemPicture src={picture} icon={visual.icon} className={cx('h-10 w-10 shrink-0', className)} />
}
