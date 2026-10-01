import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Can } from '@/auth/Can'
import { ItemPicture } from '@/components/InventoryItemCard'
import { Sheet } from '@/components/Sheet'
import { Alert, Badge, Button, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useRelativeTime } from '@/lib/format'
import { paths } from '@/lib/paths'
import type { InventoryItem, InventoryMovement, Page } from '@/lib/types'
import { inventoryKeys } from './api'
import { MovementRow } from './MovementRow'
import { useItemDisplay } from './useItemDisplay'

const RECENT = 20

/**
 * One item (tap on its card): big picture, full name, section badge, balance, Set value (with
 * inventory.adjust) and its last 20 movements, with a link to the full, filtered history.
 */
export function ItemSheet({
  item,
  onClose,
  onSet,
}: {
  item: InventoryItem | null
  onClose(): void
  onSet(item: InventoryItem): void
}) {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const relative = useRelativeTime()
  const display = useItemDisplay()

  const params = { item_code: item?.code, page_size: RECENT }
  const recent = useQuery({
    queryKey: [...inventoryKeys.movements, params],
    queryFn: async () =>
      (await api.get<Page<InventoryMovement>>('/inventory/movements', { params })).data,
    enabled: item !== null,
  })

  if (!item) return null
  const d = display(item)

  return (
    <Sheet open title={d.fullName} onClose={onClose}>
      <div className="flex items-center gap-4">
        <ItemPicture src={d.visual.picture} muted={d.visual.wasted} className="h-24 w-24" />
        <div className="min-w-0">
          <Badge tone={item.section === 'wasted' ? 'red' : 'neutral'}>
            {t(`inventory.groups.${item.group}`)}
          </Badge>
          <p className="mt-2 text-3xl font-semibold tabular-nums text-stone-900">{d.amount}</p>
          {d.secondary && (
            <p
              className="text-sm tabular-nums text-stone-500"
              title={item.kg_estimated ? t('inventory.estimatedHint') : undefined}
            >
              {d.secondary}
            </p>
          )}
          <p className="mt-1 text-xs text-stone-400">
            {item.updated_at
              ? t('inventory.updatedAgo', { time: relative(item.updated_at) })
              : t('inventory.neverChanged')}
          </p>
        </div>
      </div>

      <Can permission="inventory.adjust">
        <Button className="mt-4 w-full" onClick={() => onSet(item)}>
          {t('inventory.setValue')}
        </Button>
      </Can>

      <div className="mt-6 flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-semibold text-stone-900">{t('inventory.recentMovements')}</h3>
        <Link
          to={`${paths.inventory}?tab=history&item=${encodeURIComponent(item.code)}&section=${item.group}`}
          onClick={onClose}
          className="text-sm font-medium text-brand-700 hover:underline"
        >
          {t('inventory.seeFullHistory')}
        </Link>
      </div>
      {recent.isError && (
        <Alert tone="error" className="mt-2">
          {errorMessage(recent.error)}
        </Alert>
      )}
      {recent.isPending ? (
        <div className="flex justify-center py-6 text-brand-600">
          <Spinner />
        </div>
      ) : recent.data && recent.data.items.length === 0 ? (
        <p className="py-6 text-center text-sm text-stone-500">{t('inventory.noMovements')}</p>
      ) : (
        <ul className="-mx-4 mt-2 divide-y divide-stone-100">
          {recent.data?.items.map((m) => (
            <MovementRow key={m.id} movement={m} showItem={false} />
          ))}
        </ul>
      )}
    </Sheet>
  )
}
