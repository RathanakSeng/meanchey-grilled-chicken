import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Icon } from '@/components/icons'
import { Alert, Button, Card, Input, PageHeader, Spinner, cx } from '@/components/ui'
import { useIsMobileLayout } from '@/layouts/useIsMobileLayout'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useFormatDay } from '@/lib/format'
import { paths } from '@/lib/paths'
import type { PlanListItem, PlanPage } from '@/lib/types'
import { useDebounced } from '@/lib/useDebounced'
import { planKeys } from './api'
import { PlanStatusBadge, PlannedPacks, planStage } from './PlanBadge'

const STATUSES = ['pending', 'confirmed', 'completed', 'all'] as const
type PlanFilter = (typeof STATUSES)[number]
const PAGE_SIZE = 20

/**
 * Packaging plans: status chips (Waiting for plan by default · Confirmed · Completed · All) and a
 * search box, kept in the URL (?status=&q=&page=). Each row opens the plan.
 */
export function PlanListPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const isMobile = useIsMobileLayout()
  const formatDay = useFormatDay()
  const errorMessage = useErrorMessage()

  const [searchParams, setSearchParams] = useSearchParams()
  const statusParam = searchParams.get('status') as PlanFilter | null
  const status: PlanFilter = statusParam && STATUSES.includes(statusParam) ? statusParam : 'pending'
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

  useEffect(() => {
    if (search !== urlQ.trim()) update({ q: search || null })
  }, [search])
  useEffect(() => {
    if (urlQ.trim() !== search) setQ(urlQ)
  }, [urlQ])

  const params = { status, q: urlQ.trim() || undefined, page, page_size: PAGE_SIZE }
  const list = useQuery({
    queryKey: [...planKeys.list, params],
    queryFn: async () => (await api.get<PlanPage>('/production-plans', { params })).data,
    placeholderData: keepPreviousData,
  })
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / PAGE_SIZE)) : 1
  const open = (item: PlanListItem) => navigate(paths.productionPlan(item.batch_id))
  const pieces = (item: PlanListItem) =>
    t('plans.piecesShort', { wings: item.wings_count, thighs: item.thighs_count })

  return (
    <>
      <PageHeader
        back={paths.workstation}
        title={t('plans.title')}
        subtitle={list.data && t('plans.pendingCount', { count: list.data.pending_count })}
      />

      <div className="scrollbar-none -mx-4 mb-3 flex gap-2 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:px-0">
        {STATUSES.map((s) => (
          <button
            key={s}
            type="button"
            aria-pressed={status === s}
            onClick={() => update({ status: s === 'pending' ? null : s })}
            className={cx(
              'inline-flex min-h-9 items-center gap-1 whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium ring-1 ring-inset transition',
              status === s
                ? 'bg-brand-600 text-white ring-brand-600'
                : 'bg-white text-stone-700 ring-stone-300 hover:bg-stone-50',
            )}
          >
            {status === s && <Icon name="check" width={14} height={14} />}
            {t(`plans.filters.${s}`)}
            {s === 'pending' && list.data && list.data.pending_count > 0 && (
              <span className="tabular-nums">({list.data.pending_count})</span>
            )}
          </button>
        ))}
      </div>

      <div className="relative mb-4">
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
                <Icon name={urlQ ? 'search' : 'clipboard'} width={24} height={24} />
              </span>
              <p className="font-medium text-stone-900">
                {t(urlQ ? 'production.noResults' : status === 'pending' ? 'plans.emptyPending' : 'plans.empty')}
              </p>
              {urlQ && (
                <Button variant="secondary" className="mt-4" onClick={() => setQ('')}>
                  {t('partners.clearFilters')}
                </Button>
              )}
            </div>
          </Card>
        ) : isMobile ? (
          <ul className={cx('space-y-2', list.isPlaceholderData && 'opacity-60')}>
            {list.data.items.map((item) => (
              <li key={item.batch_id}>
                <button
                  type="button"
                  onClick={() => open(item)}
                  className="w-full rounded-xl bg-white p-3 text-left shadow-sm ring-1 ring-stone-200 active:bg-stone-50"
                >
                  <span className="flex items-start justify-between gap-2">
                    <span className="min-w-0">
                      <span className="block font-semibold tabular-nums text-stone-900">{item.code}</span>
                      <span className="block text-sm text-stone-500">
                        {item.production_date &&
                          `${t('production.datesShort.production')} ${formatDay(item.production_date, { day: 'numeric', month: 'short' })}`}
                        {item.supplier && ` · ${item.supplier.name}`}
                      </span>
                    </span>
                    <PlanStatusBadge stage={planStage(item.status, item.batch_status)} />
                  </span>
                  <span className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm text-stone-600">
                    <span className="tabular-nums">
                      {t('production.chickensCount', { count: item.quantity ?? 0 })} · {pieces(item)}
                    </span>
                    <span className="font-medium tabular-nums text-stone-800">
                      <PlannedPacks big={item.expected_big} small={item.expected_small} />
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <div
            className={cx(
              'overflow-x-auto rounded-xl bg-white shadow-sm ring-1 ring-stone-200',
              list.isPlaceholderData && 'opacity-60',
            )}
          >
            <table className="min-w-full divide-y divide-stone-200 text-sm">
              <thead className="bg-stone-50 text-left text-xs font-semibold uppercase tracking-wide text-stone-500">
                <tr>
                  <th className="px-4 py-3">{t('production.columns.code')}</th>
                  <th className="whitespace-nowrap px-4 py-3">{t('production.dates.production')}</th>
                  <th className="px-4 py-3">{t('production.fields.supplier')}</th>
                  <th className="px-4 py-3 text-right">{t('production.columns.chickens')}</th>
                  <th className="whitespace-nowrap px-4 py-3">{t('plans.columns.pieces')}</th>
                  <th className="whitespace-nowrap px-4 py-3">{t('plans.columns.planned')}</th>
                  <th className="px-4 py-3">{t('production.columns.status')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {list.data.items.map((item) => (
                  <tr key={item.batch_id} onClick={() => open(item)} className="cursor-pointer hover:bg-stone-50/60">
                    <td className="whitespace-nowrap px-4 py-3 font-medium tabular-nums text-stone-900">
                      <a
                        href={paths.productionPlan(item.batch_id)}
                        onClick={(e) => {
                          e.preventDefault()
                          open(item)
                        }}
                        className="hover:underline"
                      >
                        {item.code}
                      </a>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 tabular-nums">
                      {item.production_date ? formatDay(item.production_date) : <span className="text-stone-400">—</span>}
                    </td>
                    <td className="px-4 py-3">{item.supplier?.name ?? t('common.none')}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{item.quantity ?? t('common.none')}</td>
                    <td className="whitespace-nowrap px-4 py-3 tabular-nums">{pieces(item)}</td>
                    <td className="whitespace-nowrap px-4 py-3 tabular-nums">
                      <PlannedPacks big={item.expected_big} small={item.expected_small} />
                    </td>
                    <td className="px-4 py-3">
                      <PlanStatusBadge stage={planStage(item.status, item.batch_status)} />
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
