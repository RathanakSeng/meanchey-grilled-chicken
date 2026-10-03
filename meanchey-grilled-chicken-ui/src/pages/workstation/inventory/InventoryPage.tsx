import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { usePermission } from '@/auth/usePermission'
import { Icon } from '@/components/icons'
import { InventoryCardSkeleton, InventoryItemCard } from '@/components/InventoryItemCard'
import { Alert, PageHeader, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useRelativeTime } from '@/lib/format'
import { paths } from '@/lib/paths'
import type { InventoryGroup, InventoryItem, InventoryOverview } from '@/lib/types'
import { inventoryKeys } from './api'
import { HistoryTab } from './HistoryTab'
import { ItemSheet } from './ItemSheet'
import { useItemDisplay } from './useItemDisplay'

type Tab = 'stock' | 'history'
/** Sub-tabs of the Stock tab (`group` from the API), in order; `?section=`, default raw. */
const SECTIONS: InventoryGroup[] = ['raw', 'processed', 'packed', 'wasted']
const GRID = 'grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3 lg:grid-cols-4 xl:grid-cols-6'

/**
 * Inventory (Workstation): balances updated automatically by production (no manual changes).
 * Tabs: Stock (`?tab=stock&section=raw|processed|packed|wasted`: sub-tabs of item cards; tap a
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
        />
      )}

      <ItemSheet item={openedItem} onClose={() => setOpened(null)} />
    </>
  )
}

function hasStock(item: InventoryItem): boolean {
  return (item.count ?? 0) > 0 || Number(item.kg ?? 0) > 0
}

/** The four sub-tabs (Raw · Processed · Packed · Wasted) and the selected one's card grid. */
function StockTab({
  items,
  loading,
  section,
  onSection,
  onOpen,
}: {
  items: InventoryItem[]
  loading: boolean
  section: InventoryGroup
  onSection(section: InventoryGroup): void
  onOpen(item: InventoryItem): void
}) {
  const { t } = useTranslation()
  const allZero = !loading && items.every((i) => !hasStock(i))
  const shown = items.filter((i) => i.group === section)

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
                <ItemCard item={item} onOpen={onOpen} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  )
}

function ItemCard({ item, onOpen }: { item: InventoryItem; onOpen(item: InventoryItem): void }) {
  const { t } = useTranslation()
  const relative = useRelativeTime()
  const display = useItemDisplay()
  const d = display(item)

  return (
    <InventoryItemCard
      picture={d.visual.picture}
      mutedPicture={d.visual.wasted}
      badge={d.visual.badge && d.badgeLabel ? { tone: d.visual.badge, label: d.badgeLabel } : undefined}
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
