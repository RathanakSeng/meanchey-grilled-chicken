import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Can } from '@/auth/Can'
import { usePermission } from '@/auth/usePermission'
import { CheckboxFilter } from '@/components/CheckboxFilter'
import { Icon, type IconName } from '@/components/icons'
import { KpiGrid } from '@/components/KpiGrid'
import { Sheet } from '@/components/Sheet'
import { Alert, Button, Card, Input, PageHeader, Select, Spinner, cx } from '@/components/ui'
import { useIsMobileLayout } from '@/layouts/useIsMobileLayout'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useFormatDate, useFormatDay } from '@/lib/format'
import { paths } from '@/lib/paths'
import type { Page, Preparation, PreparationListItem, PreparationStats, PreparationType } from '@/lib/types'
import { useDebounced } from '@/lib/useDebounced'
import { ItemThumb, PreparationStatusBadge, PreparationTypeBadge, useOutputsText } from './badges'
import { onPreparationChanged, preparationKeys } from './api'

// Cancelled preparations aren't a status choice: they're shown only with "Show cancelled".
const STATUSES = ['all', 'draft', 'finished'] as const
type ListStatus = (typeof STATUSES)[number]
const TYPES: PreparationType[] = ['satay_sachet', 'packaging_material']
const PAGE_SIZE = 20

const KPIS: { key: keyof PreparationStats; labelKey: string; icon: IconName; tone: string }[] = [
  { key: 'drafts', labelKey: 'preparations.kpi.drafts', icon: 'pencil', tone: 'bg-amber-50 text-amber-700' },
  {
    key: 'finished_this_month',
    labelKey: 'preparations.kpi.finishedThisMonth',
    icon: 'check',
    tone: 'bg-green-50 text-green-700',
  },
  {
    key: 'sachets_2_this_month',
    labelKey: 'preparations.kpi.sachets2',
    icon: 'beaker',
    tone: 'bg-brand-50 text-brand-600',
  },
  {
    key: 'sachets_4_this_month',
    labelKey: 'preparations.kpi.sachets4',
    icon: 'beaker',
    tone: 'bg-brand-50 text-brand-600',
  },
]

/** "Prepared 6 Oct" once finished, else "Started 6 Oct". */
function DateLine({ item }: { item: PreparationListItem }) {
  const { t } = useTranslation()
  const formatDate = useFormatDate()
  const formatDay = useFormatDay()
  const short = { day: 'numeric', month: 'short' } as const
  return item.prepared_date ? (
    <>{t('preparations.preparedOn', { date: formatDay(item.prepared_date, short) })}</>
  ) : (
    <>{t('production.started', { date: formatDate(item.created_at, short) })}</>
  )
}

/** The New preparation sheet: two big option cards, one per type. */
function NewPreparationSheet({ open, onClose }: { open: boolean; onClose(): void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const create = useMutation({
    mutationFn: async (type: PreparationType) => (await api.post<Preparation>('/preparations', { type })).data,
    onSuccess: (p) => {
      onPreparationChanged(queryClient, p)
      navigate(paths.preparation(p.id))
    },
  })
  return (
    <Sheet open={open} title={t('preparations.new')} onClose={onClose} busy={create.isPending}>
      <p className="mb-4 text-sm text-stone-600">{t('preparations.chooseType')}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {TYPES.map((type) => (
          <button
            key={type}
            type="button"
            disabled={create.isPending}
            onClick={() => create.mutate(type)}
            className="flex flex-col items-center gap-2 rounded-2xl bg-white p-5 text-center shadow-sm ring-1 ring-stone-200 transition hover:ring-brand-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 disabled:opacity-60"
          >
            {type === 'satay_sachet' ? (
              <ItemThumb code="satay_sachet_4" className="h-16 w-16" />
            ) : (
              <span className="inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-sky-50 text-sky-700">
                <Icon name="boxes" width={32} height={32} />
              </span>
            )}
            <span className="font-semibold text-stone-900">{t(`preparations.types.${type}.title`)}</span>
            <span className="text-sm text-stone-500">{t(`preparations.types.${type}.description`)}</span>
            {create.isPending && create.variables === type && <Spinner className="h-4 w-4 text-brand-600" />}
          </button>
        ))}
      </div>
      {create.isError && (
        <Alert tone="error" className="mt-3">
          {errorMessage(create.error)}
        </Alert>
      )}
    </Sheet>
  )
}

/**
 * Preparations: figures, filters (type, status, date, search; cancelled only with "Show
 * cancelled") in the URL (?type=&status=&from=&to=&q=&cancelled=1&page=), a table on PCs and
 * cards on phones, and New preparation (choose the type).
 */
export function PreparationListPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const isMobile = useIsMobileLayout()
  const formatDay = useFormatDay()
  const errorMessage = useErrorMessage()
  const outputsText = useOutputsText()
  const canCreate = usePermission('preparation.create')
  const [creating, setCreating] = useState(false)

  const [searchParams, setSearchParams] = useSearchParams()
  const typeParam = searchParams.get('type') as PreparationType | null
  const type = typeParam && TYPES.includes(typeParam) ? typeParam : null
  const statusParam = searchParams.get('status') as ListStatus | null
  const status: ListStatus = statusParam && STATUSES.includes(statusParam) ? statusParam : 'all'
  const showCancelled = searchParams.get('cancelled') === '1'
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

  useEffect(() => {
    if (search !== urlQ.trim()) update({ q: search || null })
  }, [search])
  useEffect(() => {
    if (urlQ.trim() !== search) setQ(urlQ)
  }, [urlQ])

  const filtersActive = Boolean(type || status !== 'all' || dateFrom || dateTo || urlQ.trim() || showCancelled)
  const clearFilters = () => {
    setQ('')
    setSearchParams({}, { replace: true })
  }

  const params = {
    type: type ?? undefined,
    status,
    include_cancelled: showCancelled || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    q: urlQ.trim() || undefined,
    page,
    page_size: PAGE_SIZE,
  }
  const list = useQuery({
    queryKey: [...preparationKeys.list, params],
    queryFn: async () => (await api.get<Page<PreparationListItem>>('/preparations', { params })).data,
    placeholderData: keepPreviousData,
  })
  const stats = useQuery({
    queryKey: preparationKeys.stats,
    queryFn: async () => (await api.get<PreparationStats>('/preparations/stats')).data,
  })
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / PAGE_SIZE)) : 1

  const newButton = (
    <Can permission="preparation.create">
      <Button onClick={() => setCreating(true)}>
        <Icon name="plus" width={18} height={18} />
        {t('preparations.new')}
      </Button>
    </Can>
  )
  const open = (item: PreparationListItem) => navigate(paths.preparation(item.id))

  return (
    <>
      <PageHeader
        back={paths.workstation}
        title={t('preparations.title')}
        subtitle={list.data && t('common.total', { count: list.data.total })}
        actions={newButton}
      />

      <KpiGrid
        loading={stats.isPending}
        items={KPIS.map((kpi) => ({ ...kpi, label: t(kpi.labelKey), value: stats.data?.[kpi.key] }))}
      />

      <div className="mb-4 grid gap-2 xl:grid-cols-[1fr_auto_auto_auto_auto]">
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
            placeholder={t('preparations.searchPlaceholder')}
            aria-label={t('common.search')}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div className="grid grid-cols-2 gap-2 xl:contents">
          <Select
            aria-label={t('preparations.filters.type')}
            value={type ?? ''}
            onChange={(e) => update({ type: e.target.value || null })}
          >
            <option value="">{t('preparations.filters.allTypes')}</option>
            {TYPES.map((ty) => (
              <option key={ty} value={ty}>
                {t(`preparations.types.${ty}.short`)}
              </option>
            ))}
          </Select>
          <Select
            aria-label={t('preparations.filters.status')}
            value={status}
            onChange={(e) => update({ status: e.target.value === 'all' ? null : e.target.value })}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s === 'all' ? t('preparations.filters.allStatuses') : t(`preparations.status.${s}`)}
              </option>
            ))}
          </Select>
        </div>
        <div
          role="group"
          aria-label={t('preparations.filters.date')}
          title={t('preparations.filters.dateHint')}
          className="flex min-w-0 items-center gap-2"
        >
          <span className="shrink-0 text-sm font-medium text-stone-600">{t('production.filters.date')}</span>
          <Input
            type="date"
            className="min-w-0 flex-1 xl:w-40 xl:flex-none"
            aria-label={t('production.filters.from')}
            value={dateFrom}
            max={dateTo || undefined}
            onChange={(e) => update({ from: e.target.value || null })}
          />
          <span aria-hidden className="text-stone-400">–</span>
          <Input
            type="date"
            className="min-w-0 flex-1 xl:w-40 xl:flex-none"
            aria-label={t('production.filters.to')}
            value={dateTo}
            min={dateFrom || undefined}
            onChange={(e) => update({ to: e.target.value || null })}
          />
        </div>
        <CheckboxFilter
          label={t('production.filters.showCancelled')}
          checked={showCancelled}
          onChange={(on) => update({ cancelled: on ? '1' : null })}
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
                <Icon name={filtersActive ? 'search' : 'beaker'} width={24} height={24} />
              </span>
              {filtersActive ? (
                <>
                  <p className="font-medium text-stone-900">{t('preparations.noResults')}</p>
                  <Button variant="secondary" className="mt-4" onClick={clearFilters}>
                    {t('partners.clearFilters')}
                  </Button>
                </>
              ) : (
                <>
                  <p className="font-medium text-stone-900">{t('preparations.emptyTitle')}</p>
                  <p className="mt-1 max-w-sm text-sm text-stone-500">
                    {t(canCreate ? 'preparations.emptyBody' : 'preparations.emptyBodyReadOnly')}
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
                        <DateLine item={item} />
                      </span>
                    </span>
                    <PreparationStatusBadge status={item.status} />
                  </span>
                  <span className="mt-2 flex items-start justify-between gap-2 text-sm text-stone-600">
                    <span className="min-w-0">{outputsText(item.outputs)}</span>
                    <PreparationTypeBadge type={item.type} />
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
                  <th className="rounded-tl-xl px-4 py-3">{t('preparations.columns.code')}</th>
                  <th className="px-4 py-3">{t('preparations.columns.type')}</th>
                  <th className="px-4 py-3">{t('preparations.columns.outputs')}</th>
                  <th className="whitespace-nowrap px-4 py-3">{t('preparations.columns.preparedDate')}</th>
                  <th className="rounded-tr-xl px-4 py-3">{t('preparations.columns.status')}</th>
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
                        href={paths.preparation(item.id)}
                        onClick={(e) => {
                          e.preventDefault()
                          open(item)
                        }}
                        className="hover:underline"
                      >
                        {item.code}
                      </a>
                    </td>
                    <td className="px-4 py-3">
                      <PreparationTypeBadge type={item.type} />
                    </td>
                    <td className="px-4 py-3">{outputsText(item.outputs)}</td>
                    <td className="whitespace-nowrap px-4 py-3 tabular-nums">
                      {item.prepared_date ? formatDay(item.prepared_date) : <span className="text-stone-400">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      <PreparationStatusBadge status={item.status} />
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

      <NewPreparationSheet open={creating} onClose={() => setCreating(false)} />
    </>
  )
}
