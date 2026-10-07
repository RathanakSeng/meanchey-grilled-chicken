import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { usePermission } from '@/auth/usePermission'
import { Icon } from '@/components/icons'
import { InventoryCardSkeleton, InventoryItemCard } from '@/components/InventoryItemCard'
import { Alert, Button, PageHeader, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useLocalized, useRelativeTime } from '@/lib/format'
import { paths } from '@/lib/paths'
import type { InventoryGroup, InventoryItem, InventoryOverview, Material } from '@/lib/types'
import { inventoryKeys, invalidateInventory } from './api'
import { HistoryTab } from './HistoryTab'
import { ItemSheet } from './ItemSheet'
import { MaterialFormSheet, StockSheet, materialRefOfItem, type MaterialRef } from './MaterialSheets'
import { useItemPicture } from './materialIcons'
import { useItemDisplay } from './useItemDisplay'

type Tab = 'stock' | 'history'
/** Sub-tabs of the Stock tab (`group` from the API), in order; `?section=`, default raw. */
const SECTIONS: InventoryGroup[] = ['raw', 'processed', 'packed', 'prepared', 'wasted']
const GRID = 'grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3 lg:grid-cols-4 xl:grid-cols-6'

/**
 * Inventory (Workstation): balances updated by production and orders, plus **materials** in Raw
 * (string, skewers, sauces…: stock added / removed by hand with Inventory Record; created, edited
 * and archived with Inventory materials). Tabs: Stock (`?tab=stock&section=raw|processed|packed|prepared|wasted`: sub-tabs of item cards; tap a
 * card for its sheet) and History (`?tab=history`, with its filters; only with inventory.history:
 * without it there is no tab bar and Stock shows directly). The section is kept when switching
 * tabs, so Back and refresh return to the same sub-tab.
 */
export function InventoryPage() {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const [searchParams, setSearchParams] = useSearchParams()
  const canSeeHistory = usePermission('inventory.history')
  const tab: Tab = canSeeHistory && searchParams.get('tab') === 'history' ? 'history' : 'stock'
  const sectionParam = searchParams.get('section') as InventoryGroup | null
  const section: InventoryGroup =
    sectionParam && SECTIONS.includes(sectionParam) ? sectionParam : 'raw'
  const [opened, setOpened] = useState<string | null>(null)
  // A material's Add sheet straight from its card.
  const [adding, setAdding] = useState<MaterialRef | null>(null)
  const [creating, setCreating] = useState(false)

  const overview = useQuery({
    queryKey: inventoryKeys.overview,
    queryFn: async () => (await api.get<InventoryOverview>('/inventory')).data,
  })
  const items = overview.data?.sections.flatMap((s) => s.items) ?? []
  // By code, so the open sheet shows fresh numbers after a Set value.
  const openedItem = items.find((i) => i.code === opened) ?? null

  return (
    <>
      <PageHeader back={paths.workstation} title={t('inventory.title')} subtitle={t('inventory.subtitle')} />

      {canSeeHistory && (
        <div className="mb-4 flex gap-1 border-b border-stone-200">
          {(['stock', 'history'] as const).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setSearchParams({ tab: key, section }, { replace: true })}
              className={cx(
                '-mb-px border-b-2 px-4 py-2 text-sm font-medium',
                tab === key
                  ? 'border-brand-600 text-brand-700'
                  : 'border-transparent text-stone-500 hover:text-stone-800',
              )}
            >
              {t(`inventory.tabs.${key}`)}
            </button>
          ))}
        </div>
      )}

      {overview.isError && <Alert tone="error">{errorMessage(overview.error)}</Alert>}

      {tab === 'history' ? (
        <HistoryTab items={items} />
      ) : overview.isError ? null : (
        <StockTab
          items={items}
          loading={overview.isPending}
          section={section}
          onSection={(next) => setSearchParams({ tab: 'stock', section: next }, { replace: true })}
          onOpen={(item) => setOpened(item.code)}
          onAdd={(item) => setAdding(materialRefOfItem(item))}
          onCreate={() => setCreating(true)}
        />
      )}

      <ItemSheet item={openedItem} onClose={() => setOpened(null)} />
      <StockSheet material={adding} mode="add" open={adding !== null} onClose={() => setAdding(null)} />
      {creating && <MaterialFormSheet material={null} open onClose={() => setCreating(false)} />}
    </>
  )
}

function hasStock(item: InventoryItem): boolean {
  return (item.count ?? 0) > 0 || Number(item.kg ?? 0) > 0 || Number(item.g ?? 0) > 0
}

/** An archived material as a card item (it isn't in the overview). */
function archivedItem(m: Material): InventoryItem {
  return {
    code: m.item_code,
    section: 'stock',
    group: 'raw',
    name_km: m.name_km,
    name_en: m.name_en,
    tracks_count: m.unit === 'count',
    tracks_kg: m.unit === 'kg',
    tracks_g: m.unit === 'g',
    kg_estimated: false,
    origin: 'manual',
    count: m.count,
    kg: m.kg,
    g: m.g,
    // When it was archived (its last change).
    updated_at: m.archived_at ?? m.updated_at,
    material: {
      id: m.id,
      unit: m.unit,
      system_code: m.system_code,
      archived: true,
      icon_key: m.icon_key,
      icon_url: m.icon_url,
    },
  }
}

/** The four sub-tabs (Raw · Processed · Packed · Wasted) and the selected one's card grid. */
function StockTab({
  items,
  loading,
  section,
  onSection,
  onOpen,
  onAdd,
  onCreate,
}: {
  items: InventoryItem[]
  loading: boolean
  section: InventoryGroup
  onSection(section: InventoryGroup): void
  onOpen(item: InventoryItem): void
  onAdd(item: InventoryItem): void
  onCreate(): void
}) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const errorMessage = useErrorMessage()
  const queryClient = useQueryClient()
  const canStock = usePermission('inventory.materials_stock')
  const canManage = usePermission('inventory.materials_manage')
  const [showArchived, setShowArchived] = useState(false)
  const allZero = !loading && items.every((i) => !hasStock(i))
  // Raw: Chicken first, then the materials by name in the UI language.
  const shown = items
    .filter((i) => i.group === section)
    .sort((a, b) =>
      a.material && b.material ? localized(a).localeCompare(localized(b)) : a.material ? 1 : b.material ? -1 : 0,
    )
  // (Prepared: the satay sachets first, then the prepared materials by name — same rule.)
  const archived = useQuery({
    queryKey: inventoryKeys.materials({ include_archived: true }),
    queryFn: async () =>
      (await api.get<Material[]>('/inventory/materials', { params: { include_archived: true } })).data,
    enabled: canManage && showArchived && section === 'raw',
  })
  const archivedItems = (archived.data ?? [])
    .filter((m) => m.archived_at !== null)
    .map(archivedItem)
    .sort((a, b) => localized(a).localeCompare(localized(b)))
  const restore = useMutation({
    mutationFn: async (id: string) => api.post(`/inventory/materials/${id}/restore`),
    onSuccess: () => invalidateInventory(queryClient),
  })

  return (
    <>
      {allZero && (
        <Alert className="mb-4">
          <span className="flex items-start gap-2">
            <Icon name="boxes" width={18} height={18} className="mt-0.5 shrink-0" />
            {t('inventory.empty')}
          </span>
        </Alert>
      )}

      {/* Sub-tabs: pills, lighter than the main tabs above. Equal widths on phones (scrolls if a
          label doesn't fit), left-aligned from sm. */}
      <div
        role="tablist"
        aria-label={t('inventory.tabs.stock')}
        className="scrollbar-none -mx-4 mb-4 overflow-x-auto px-4 sm:mx-0 sm:px-0"
      >
        <div className="grid min-w-full auto-cols-[minmax(max-content,1fr)] grid-flow-col gap-1 rounded-full bg-stone-100 p-1 sm:inline-grid sm:min-w-0 sm:auto-cols-auto">
          {SECTIONS.map((key) => {
            const selected = key === section
            const stocked = items.filter((i) => i.group === key && hasStock(i)).length
            const wasted = key === 'wasted'
            return (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={selected}
                onClick={() => onSection(key)}
                className={cx(
                  'inline-flex min-h-9 items-center justify-center gap-1.5 whitespace-nowrap rounded-full px-2 py-1.5 sm:px-3 text-sm font-medium transition',
                  'focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500',
                  selected
                    ? wasted
                      ? 'bg-red-50 text-red-700 shadow-sm ring-1 ring-red-200'
                      : 'bg-white text-stone-900 shadow-sm ring-1 ring-stone-200'
                    : 'text-stone-600 hover:text-stone-900',
                )}
              >
                {t(`inventory.groups.${key}`)}
                {/* Items in this tab with stock; hidden at 0 and while loading. */}
                {!loading && stocked > 0 && (
                  <span
                    className={cx(
                      'min-w-5 rounded-full px-1.5 text-xs tabular-nums',
                      wasted ? 'bg-red-100 text-red-700' : 'bg-stone-200 text-stone-700',
                    )}
                    aria-label={t('inventory.inStockCount', { count: stocked })}
                  >
                    {stocked}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {section === 'raw' && canManage && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <label className="inline-flex items-center gap-2 text-sm text-stone-700">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
              className="h-4 w-4 rounded border-stone-300 text-brand-600 focus:ring-brand-500"
            />
            {t('materials.showArchived')}
          </label>
          <Button onClick={onCreate}>
            <Icon name="plus" width={18} height={18} />
            {t('materials.newTitle')}
          </Button>
        </div>
      )}
      {restore.isError && (
        <Alert tone="error" className="mb-3">
          {errorMessage(restore.error)}
        </Alert>
      )}

      <div role="tabpanel">
        {loading ? (
          <ul className={GRID} aria-busy>
            {Array.from({ length: 6 }, (_, j) => (
              <li key={j}>
                <InventoryCardSkeleton />
              </li>
            ))}
          </ul>
        ) : shown.length === 0 ? (
          <p className="rounded-xl bg-white py-10 text-center text-sm text-stone-500 ring-1 ring-stone-200">
            {t('inventory.emptySection')}
          </p>
        ) : (
          <ul className={GRID}>
            {shown.map((item) => (
              <li key={item.code}>
                <ItemCard
                  item={item}
                  onOpen={onOpen}
                  onAdd={item.origin === 'manual' && canStock ? onAdd : undefined}
                />
              </li>
            ))}
          </ul>
        )}
        {section === 'raw' && showArchived && archivedItems.length > 0 && (
          <>
            <h3 className="mb-2 mt-6 text-sm font-semibold text-stone-500">{t('materials.archivedTitle')}</h3>
            <ul className={cx(GRID, 'opacity-60')}>
              {archivedItems.map((item) => (
                <li key={item.code}>
                  <ItemCard
                    item={item}
                    onOpen={() => undefined}
                    action={
                      <Button
                        variant="secondary"
                        block
                        loading={restore.isPending && restore.variables === item.material?.id}
                        onClick={() => item.material && restore.mutate(item.material.id)}
                      >
                        {t('materials.restore')}
                      </Button>
                    }
                  />
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </>
  )
}

function ItemCard({
  item,
  onOpen,
  onAdd,
  action,
}: {
  item: InventoryItem
  onOpen(item: InventoryItem): void
  /** Materials with Inventory Record: a "+ Add" button on the card. */
  onAdd?(item: InventoryItem): void
  action?: React.ReactNode
}) {
  const { t } = useTranslation()
  const relative = useRelativeTime()
  const display = useItemDisplay()
  const d = display(item)
  const picture = useItemPicture(d.visual)
  const system = item.material?.system_code
  const badge =
    d.visual.badge && d.badgeLabel
      ? { tone: d.visual.badge, label: d.badgeLabel }
      : item.material?.archived
        ? { tone: 'archived' as const, label: t('materials.archivedBadge') }
        : system
          ? { tone: 'system' as const, label: t('materials.usedByProduction') }
          : undefined

  return (
    <InventoryItemCard
      picture={picture}
      icon={d.visual.icon}
      mutedPicture={d.visual.wasted}
      badge={badge}
      action={
        action ??
        (onAdd && (
          <Button variant="soft" block onClick={() => onAdd(item)}>
            <Icon name="plus" width={16} height={16} />
            {t('materials.add')}
          </Button>
        ))
      }
      name={d.shortName}
      amount={d.amount}
      secondary={
        d.secondary && (
          <span title={item.kg_estimated ? t('inventory.estimatedHint') : undefined}>{d.secondary}</span>
        )
      }
      updated={
        item.updated_at ? t('inventory.updatedAgo', { time: relative(item.updated_at) }) : t('inventory.neverChanged')
      }
      zero={d.zero}
      ariaLabel={t('inventory.cardLabel', {
        // Wasted items share the stock names: say which one it is.
        name: d.visual.wasted && d.badgeLabel ? `${d.fullName} · ${d.badgeLabel}` : d.fullName,
        amount: d.secondary ? `${d.amount} · ${d.secondary}` : d.amount,
      })}
      onOpen={() => onOpen(item)}
    />
  )
}
