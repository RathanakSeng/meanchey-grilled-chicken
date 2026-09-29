import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Can } from '@/auth/Can'
import { usePermission } from '@/auth/usePermission'
import { Icon, type IconName } from '@/components/icons'
import { KpiGrid } from '@/components/KpiGrid'
import { Alert, Button, Card, Input, PageHeader, Select, Spinner, cx } from '@/components/ui'
import { useIsMobileLayout } from '@/layouts/useIsMobileLayout'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useFormatDate } from '@/lib/format'
import { paths } from '@/lib/paths'
import type { Page, ProductionBatch, ProductionBatchListItem, ProductionStats } from '@/lib/types'
import { useDebounced } from '@/lib/useDebounced'
import { onBatchChanged, productionKeys } from './api'
import { BatchStatusBadge, StepDots } from './badges'

const STATUSES = ['all', 'in_progress', 'completed', 'cancelled'] as const
type ListStatus = (typeof STATUSES)[number]
const PAGE_SIZE = 20

const KPIS: { key: keyof ProductionStats; labelKey: string; icon: IconName; tone: string }[] = [
  { key: 'in_progress', labelKey: 'production.kpi.inProgress', icon: 'restore', tone: 'bg-amber-50 text-amber-700' },
  { key: 'completed_today', labelKey: 'production.kpi.completedToday', icon: 'check', tone: 'bg-green-50 text-green-700' },
  { key: 'chickens_this_month', labelKey: 'production.kpi.chickensThisMonth', icon: 'chicken', tone: 'bg-brand-50 text-brand-600' },
  {
    key: 'rejected_pieces_this_month',
    labelKey: 'production.kpi.rejectedThisMonth',
    icon: 'alert',
    tone: 'bg-stone-100 text-stone-600',
  },
]

function Kpis({ stats, loading }: { stats: ProductionStats | undefined; loading: boolean }) {
  const { t } = useTranslation()
  return (
    <KpiGrid
      loading={loading}
      items={KPIS.map((kpi) => ({ ...kpi, label: t(kpi.labelKey), value: stats?.[kpi.key] }))}
    />
  )
}

function Chip({ active, onClick, children }: { active: boolean; onClick(): void; children: string }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cx(
        'inline-flex min-h-9 items-center gap-1 whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium ring-1 ring-inset transition',
        active ? 'bg-brand-600 text-white ring-brand-600' : 'bg-white text-stone-700 ring-stone-300 hover:bg-stone-50',
      )}
    >
      {active && <Icon name="check" width={14} height={14} />}
      {children}
    </button>
  )
}

/**
 * Production batches: figures, quick filters ("waiting for step 2 / 3"), status, dates and search.
 * Filters live in the URL (?waiting=&status=&from=&to=&q=&page=).
 */
export function ProductionListPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const isMobile = useIsMobileLayout()
  const formatDate = useFormatDate()
  const errorMessage = useErrorMessage()
  const queryClient = useQueryClient()
  const canCreate = usePermission('production.create')

  const [searchParams, setSearchParams] = useSearchParams()
  const waiting = ['2', '3'].includes(searchParams.get('waiting') ?? '') ? searchParams.get('waiting') : null
  const statusParam = searchParams.get('status') as ListStatus | null
  const status: ListStatus = statusParam && STATUSES.includes(statusParam) ? statusParam : 'all'
  const dateFrom = searchParams.get('from') ?? ''
  const dateTo = searchParams.get('to') ?? ''
  const page = Math.max(1, Number(searchParams.get('page')) || 1)
  const urlQ = searchParams.get('q') ?? ''
  const [q, setQ] = useState(urlQ)
  const search = useDebounced(q.trim())

  const update = (changes: Record<string, string | null>) =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [k, v] of Object.entries(changes)) {
          if (v === null || v === '') next.delete(k)
          else next.set(k, v)
        }
        if (!('page' in changes)) next.delete('page')
        return next
      },
      { replace: true },
    )

  // Same search-box ↔ URL sync as the partner lists.
  useEffect(() => {
    if (search !== urlQ.trim()) update({ q: search || null })
  }, [search])
  useEffect(() => {
    if (urlQ.trim() !== search) setQ(urlQ)
  }, [urlQ])

  const filtersActive = Boolean(waiting || status !== 'all' || dateFrom || dateTo || urlQ.trim())
  const clearFilters = () => {
    setQ('')
    setSearchParams({}, { replace: true })
  }

  const params = {
    waiting_step: waiting ?? undefined,
    status,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    q: urlQ.trim() || undefined,
    page,
    page_size: PAGE_SIZE,
  }
  const list = useQuery({
    queryKey: [...productionKeys.list, params],
    queryFn: async () => (await api.get<Page<ProductionBatchListItem>>('/production', { params })).data,
    placeholderData: keepPreviousData,
  })
  const stats = useQuery({
    queryKey: productionKeys.stats,
    queryFn: async () => (await api.get<ProductionStats>('/production/stats')).data,
  })
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / PAGE_SIZE)) : 1

  const create = useMutation({
    mutationFn: async () => (await api.post<ProductionBatch>('/production', {})).data,
    onSuccess: (batch) => {
      onBatchChanged(queryClient, batch)
      navigate(paths.productionBatch(batch.id, 1))
    },
  })

  const newButton = (
    <Can permission="production.create">
      <Button onClick={() => create.mutate()} loading={create.isPending}>
        <Icon name="plus" width={18} height={18} />
        {t('production.new')}
      </Button>
    </Can>
  )
  const open = (item: ProductionBatchListItem) => navigate(paths.productionBatch(item.id))
  const chickens = (n: number | null) => (n === null ? t('common.none') : String(n))

  return (
    <>
      <PageHeader
        back={paths.workstation}
        title={t('production.title')}
        subtitle={list.data && t('common.total', { count: list.data.total })}
        actions={newButton}
      />
      {create.isError && (
        <Alert tone="error" className="mb-4">
          {errorMessage(create.error)}
        </Alert>
      )}

      <Kpis stats={stats.data} loading={stats.isPending} />

      <div className="scrollbar-none -mx-4 mb-3 flex gap-2 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:px-0">
        <Chip active={waiting === '2'} onClick={() => update({ waiting: waiting === '2' ? null : '2' })}>
          {t('production.filters.waiting2')}
        </Chip>
        <Chip active={waiting === '3'} onClick={() => update({ waiting: waiting === '3' ? null : '3' })}>
          {t('production.filters.waiting3')}
        </Chip>
      </div>

      <div className="mb-4 grid gap-2 lg:grid-cols-[1fr_auto_auto_auto]">
        <div className="relative">
          <Icon
            name="search"
            width={16}
            height={16}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-400"
          />
          <Input
            type="search"
            className="pl-9"
            placeholder={t('production.searchPlaceholder')}
            aria-label={t('common.search')}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div className="grid grid-cols-3 gap-2 lg:contents">
          <Select
            aria-label={t('production.filters.status')}
            value={status}
            onChange={(e) => update({ status: e.target.value === 'all' ? null : e.target.value })}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s === 'all' ? t('production.filters.allStatuses') : t(`production.status.${s}`)}
              </option>
            ))}
          </Select>
          <Input
            type="date"
            aria-label={t('production.filters.from')}
            title={t('production.filters.from')}
            value={dateFrom}
            max={dateTo || undefined}
            onChange={(e) => update({ from: e.target.value || null })}
          />
          <Input
            type="date"
            aria-label={t('production.filters.to')}
            title={t('production.filters.to')}
            value={dateTo}
            min={dateFrom || undefined}
            onChange={(e) => update({ to: e.target.value || null })}
          />
        </div>
      </div>

      {list.isError && <Alert tone="error">{errorMessage(list.error)}</Alert>}
      {list.isPending && (
        <div className="flex justify-center py-10 text-brand-600">
          <Spinner />
        </div>
      )}

      {list.data &&
        (list.data.items.length === 0 ? (
          <Card>
            <div className="flex flex-col items-center py-8 text-center">
              <span className="mb-3 inline-flex h-12 w-12 items-center justify-center rounded-full bg-brand-50 text-brand-600">
                <Icon name={filtersActive ? 'search' : 'chicken'} width={24} height={24} />
              </span>
              {filtersActive ? (
                <>
                  <p className="font-medium text-stone-900">{t('production.noResults')}</p>
                  <Button variant="secondary" className="mt-4" onClick={clearFilters}>
                    {t('partners.clearFilters')}
                  </Button>
                </>
              ) : (
                <>
                  <p className="font-medium text-stone-900">{t('production.emptyTitle')}</p>
                  <p className="mt-1 max-w-sm text-sm text-stone-500">
                    {t(canCreate ? 'production.emptyBody' : 'production.emptyBodyReadOnly')}
                  </p>
                  {canCreate && <div className="mt-4">{newButton}</div>}
                </>
              )}
            </div>
          </Card>
        ) : isMobile ? (
          <ul className={cx('space-y-2', list.isPlaceholderData && 'opacity-60')}>
            {list.data.items.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => open(item)}
                  className={cx(
                    'w-full rounded-xl bg-white p-3 text-left shadow-sm ring-1 ring-stone-200 active:bg-stone-50',
                    item.status === 'cancelled' && 'opacity-60',
                  )}
                >
                  <span className="flex items-start justify-between gap-2">
                    <span className="min-w-0">
                      <span className="block font-semibold tabular-nums text-stone-900">{item.code}</span>
                      <span className="block text-sm text-stone-500">
                        {formatDate(item.production_date, { dateStyle: 'medium' })}
                        {item.supplier && ` · ${item.supplier.name}`}
                      </span>
                    </span>
                    <BatchStatusBadge status={item.status} />
                  </span>
                  <span className="mt-2 flex items-center justify-between text-sm text-stone-600">
                    <StepDots steps={item.steps} />
                    <span className="tabular-nums">
                      {t('production.chickensCount', { count: item.quantity ?? 0 })}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <div className={cx('rounded-xl bg-white shadow-sm ring-1 ring-stone-200', list.isPlaceholderData && 'opacity-60')}>
            <table className="min-w-full divide-y divide-stone-200 text-sm">
              <thead className="bg-stone-50 text-left text-xs font-semibold uppercase tracking-wide text-stone-500">
                <tr>
                  <th className="rounded-tl-xl px-4 py-3">{t('production.columns.code')}</th>
                  <th className="px-4 py-3">{t('production.fields.date')}</th>
                  <th className="px-4 py-3">{t('production.fields.supplier')}</th>
                  <th className="px-4 py-3">{t('production.columns.steps')}</th>
                  <th className="px-4 py-3 text-right">{t('production.columns.chickens')}</th>
                  <th className="rounded-tr-xl px-4 py-3">{t('production.columns.status')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {list.data.items.map((item) => (
                  <tr
                    key={item.id}
                    onClick={() => open(item)}
                    className={cx('cursor-pointer hover:bg-stone-50/60', item.status === 'cancelled' && 'text-stone-400')}
                  >
                    <td className="whitespace-nowrap px-4 py-3 font-medium tabular-nums text-stone-900">
                      <a
                        href={paths.productionBatch(item.id)}
                        onClick={(e) => {
                          e.preventDefault()
                          open(item)
                        }}
                        className="hover:underline"
                      >
                        {item.code}
                      </a>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      {formatDate(item.production_date, { dateStyle: 'medium' })}
                    </td>
                    <td className="px-4 py-3">{item.supplier?.name ?? t('common.none')}</td>
                    <td className="px-4 py-3">
                      <StepDots steps={item.steps} />
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">{chickens(item.quantity)}</td>
                    <td className="px-4 py-3">
                      <BatchStatusBadge status={item.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}

      {list.data && pages > 1 && (
        <div className="mt-4 flex items-center justify-between gap-2 text-sm text-stone-600">
          <Button variant="secondary" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}>
            {t('common.previous')}
          </Button>
          <span>{t('common.pageOf', { page, pages })}</span>
          <Button variant="secondary" disabled={page >= pages} onClick={() => update({ page: String(page + 1) })}>
            {t('common.next')}
          </Button>
        </div>
      )}
    </>
  )
}
