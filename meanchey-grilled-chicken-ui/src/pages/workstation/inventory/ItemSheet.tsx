import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { usePermission } from '@/auth/usePermission'
import { ActionMenu, type ActionMenuItem } from '@/components/ActionMenu'
import { Icon } from '@/components/icons'
import { ItemPicture } from '@/components/InventoryItemCard'
import { Sheet } from '@/components/Sheet'
import { Alert, Badge, Button, ConfirmDialog, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useRelativeTime } from '@/lib/format'
import { paths } from '@/lib/paths'
import type { InventoryItem, InventoryItemDetail, InventoryMovement, ItemSource, Page } from '@/lib/types'
import { STEPS } from '@/pages/workstation/production/api'
import { invalidateInventory, inventoryKeys, useStockFormat } from './api'
import { MaterialFormSheet, StockSheet, materialRefOfItem } from './MaterialSheets'
import { MovementRow } from './MovementRow'
import { useItemPicture } from './materialIcons'
import { useItemDisplay } from './useItemDisplay'
import { itemVisual } from './itemVisuals'

const RECENT = 20

/**
 * One item (tap on its card): big picture, full name, its sub-tab, the balance, and **From
 * production**: what each batch currently contributes (everyone with Inventory). With
 * inventory.history also its last 20 movements and a link to the full, filtered history.
 *
 * Materials instead get **Add** / **Remove** (Inventory Record) and ⋮ **Edit** / **Archive**
 * (Inventory materials; a system material like Marinade sauce can't be archived). Those open in
 * place of this sheet and come back to it.
 */
export function ItemSheet({ item, onClose }: { item: InventoryItem | null; onClose(): void }) {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const relative = useRelativeTime()
  const display = useItemDisplay()
  const queryClient = useQueryClient()
  const canSeeHistory = usePermission('inventory.history')
  const canStock = usePermission('inventory.materials_stock')
  const canManage = usePermission('inventory.materials_manage')
  const [mode, setMode] = useState<'view' | 'add' | 'remove' | 'edit' | 'archive'>('view')
  const archive = useMutation({
    mutationFn: async (id: string) => api.post(`/inventory/materials/${id}/archive`),
    onSuccess: () => {
      invalidateInventory(queryClient)
      setMode('view')
      onClose()
    },
  })

  const detail = useQuery({
    queryKey: inventoryKeys.item(item?.code ?? ''),
    queryFn: async () => (await api.get<InventoryItemDetail>(`/inventory/items/${item?.code}`)).data,
    enabled: item !== null,
  })
  const params = { item_code: item?.code, page_size: RECENT }
  const recent = useQuery({
    queryKey: [...inventoryKeys.movements, params],
    queryFn: async () =>
      (await api.get<Page<InventoryMovement>>('/inventory/movements', { params })).data,
    enabled: item !== null && canSeeHistory,
  })

  // The detail is refetched after an edit (a new icon) while the sheet stays open.
  const picture = useItemPicture(item ? itemVisual(detail.data ?? item) : null)

  if (!item) return null
  const d = display(item)
  const material = materialRefOfItem(item)
  const back = () => setMode('view')
  if (material && (mode === 'add' || mode === 'remove')) {
    return <StockSheet material={material} mode={mode} open onClose={back} />
  }
  if (material && mode === 'edit') {
    return <MaterialFormSheet key={material.id} material={material} open onClose={back} />
  }
  const menu: ActionMenuItem[] =
    material && canManage
      ? [
          { key: 'edit', label: t('common.edit'), icon: 'pencil', onSelect: () => setMode('edit') },
          ...(material.system_code
            ? []
            : [
                {
                  key: 'archive',
                  label: t('materials.archive'),
                  icon: 'archive' as const,
                  tone: 'danger' as const,
                  onSelect: () => setMode('archive'),
                },
              ]),
        ]
      : []

  return (
    <Sheet open title={d.fullName} onClose={onClose}>
      <div className="flex items-center gap-4">
        <ItemPicture src={picture} icon={d.visual.icon} muted={d.visual.wasted} className="h-24 w-24" />
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
        {menu.length > 0 && (
          <div className="ml-auto self-start">
            <ActionMenu items={menu} label={t('materials.actions')} />
          </div>
        )}
      </div>

      {material ? (
        <>
          {material.system_code && (
            <p className="mt-4 rounded-lg bg-sky-50 px-3 py-2 text-sm text-sky-800 ring-1 ring-inset ring-sky-200">
              {t('materials.systemNote')}
            </p>
          )}
          {canStock && (
            <div className="mt-4 grid grid-cols-2 gap-2">
              <Button onClick={() => setMode('add')}>
                <Icon name="plus" width={18} height={18} />
                {t('materials.add')}
              </Button>
              <Button variant="secondary" onClick={() => setMode('remove')}>
                {t('materials.remove')}
              </Button>
            </div>
          )}
        </>
      ) : (
        <>
          <h3 className="mt-6 text-sm font-semibold text-stone-900">{t('inventory.fromProduction')}</h3>
          {detail.isError && (
            <Alert tone="error" className="mt-2">
              {errorMessage(detail.error)}
            </Alert>
          )}
          {detail.isPending ? (
            <div className="flex justify-center py-6 text-brand-600">
              <Spinner />
            </div>
          ) : detail.data ? (
            <Sources detail={detail.data} onNavigate={onClose} />
          ) : null}
        </>
      )}

      {canSeeHistory && (
        <>
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
        </>
      )}
      {material && (
        <ConfirmDialog
          open={mode === 'archive'}
          title={t('materials.archiveTitle', { name: d.fullName })}
          body={
            Number(item.count ?? item.kg ?? item.g ?? 0) > 0
              ? t('materials.archiveWithStock', { amount: d.amount })
              : t('materials.archiveBody')
          }
          confirmLabel={t('materials.archive')}
          tone="danger"
          loading={archive.isPending}
          error={archive.isError ? errorMessage(archive.error) : null}
          onConfirm={() => archive.mutate(material.id)}
          onClose={() => {
            archive.reset()
            back()
          }}
        />
      )}
    </Sheet>
  )
}

/** One row per batch (oldest first) and a totals line equal to the balance. */
function Sources({ detail, onNavigate }: { detail: InventoryItemDetail; onNavigate(): void }) {
  const { t } = useTranslation()
  const fmt = useStockFormat()

  if (detail.sources.length === 0) {
    return <p className="py-4 text-sm text-stone-500">{t('inventory.noProductionStock')}</p>
  }
  const amount = (s: Pick<ItemSource, 'count' | 'kg' | 'kg_estimated'>) =>
    [
      s.count !== null && fmt.count(s.count),
      s.kg !== null && `${s.kg_estimated ? '≈ ' : ''}${fmt.kg(s.kg)}`,
    ]
      .filter(Boolean)
      .join(' · ')

  return (
    <ul className="mt-2 divide-y divide-stone-100 text-sm">
      {detail.sources.map((s) => (
        <li key={s.batch_id} className="flex items-baseline justify-between gap-3 py-2">
          <span className="min-w-0">
            <Link
              to={paths.productionBatch(s.batch_id, s.last_step)}
              onClick={onNavigate}
              className="font-medium tabular-nums text-brand-700 hover:underline"
            >
              {s.code}
            </Link>
            <span className="text-stone-500"> · {t(STEPS[s.last_step - 1].labelKey)}</span>
          </span>
          <span
            className="shrink-0 font-medium tabular-nums text-stone-900"
            title={s.kg_estimated ? t('inventory.estimatedHint') : undefined}
          >
            {amount(s)}
          </span>
        </li>
      ))}
      <li className="flex items-baseline justify-between gap-3 py-2 font-semibold text-stone-900">
        <span>{t('inventory.total')}</span>
        <span className="tabular-nums">
          {amount({
            count: detail.count,
            kg: detail.kg,
            kg_estimated: detail.sources.some((s) => s.kg_estimated),
          })}
        </span>
      </li>
    </ul>
  )
}
