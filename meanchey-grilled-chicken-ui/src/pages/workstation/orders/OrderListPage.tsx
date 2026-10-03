import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Can } from '@/auth/Can'
import { usePermission } from '@/auth/usePermission'
import { Icon, type IconName } from '@/components/icons'
import { KpiGrid } from '@/components/KpiGrid'
import { Alert, Button, Card, Input, PageHeader, Select, Spinner, cx } from '@/components/ui'
import { useIsMobileLayout } from '@/layouts/useIsMobileLayout'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useFormatDay } from '@/lib/format'
import { paths } from '@/lib/paths'
import type { CustomerOption, OrderListItem, OrderStats, Page } from '@/lib/types'
import { useDebounced } from '@/lib/useDebounced'
import { orderKeys } from './api'
import { BoxCounts, OrderStatusBadge } from './badges'

// Chips; "completed" = success, partly or fully returned.
const STATUSES = ['all', 'created', 'delivering', 'return_pending', 'completed', 'cancelled'] as const
type ListStatus = (typeof STATUSES)[number]
const PAGE_SIZE = 20

const KPIS: { key: keyof OrderStats; labelKey: string; icon: IconName; tone: string; status?: ListStatus }[] = [
  { key: 'created', labelKey: 'orders.kpi.created', icon: 'clipboard', tone: 'bg-stone-100 text-stone-700', status: 'created' },
  { key: 'delivering', labelKey: 'orders.kpi.delivering', icon: 'truck', tone: 'bg-sky-50 text-sky-700', status: 'delivering' },
  {
    key: 'return_pending',
    labelKey: 'orders.kpi.returnPending',
    icon: 'restore',
    tone: 'bg-amber-50 text-amber-700',
    status: 'return_pending',
  },
  { key: 'delivered_this_month', labelKey: 'orders.kpi.deliveredThisMonth', icon: 'check', tone: 'bg-green-50 text-green-700' },
]

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

/** Customer filter, from the form's customer options (only for people who record or edit). */
function CustomerFilter({ value, onChange }: { value: string; onChange(id: string | null): void }) {
  const { t } = useTranslation()
  const options = useQuery({
    queryKey: orderKeys.customerOptions(''),
    queryFn: async () => (await api.get<CustomerOption[]>('/orders/customer-options')).data,
  })
  return (
    <Select aria-label={t('orders.filters.customer')} value={value} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">{t('orders.filters.allCustomers')}</option>
      {options.data?.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
        </option>
      ))}
    </Select>
  )
}

/**
 * Orders: figures (Created · Delivering · Return pending · Delivered this month), status chips,
 * customer and delivery-date filters and search, all in the URL
 * (?status=&customer=&from=&to=&q=&page=). Cards on phones, a table on desktop.
 */
export function OrderListPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const isMobile = useIsMobileLayout()
  const formatDay = useFormatDay()
  const errorMessage = useErrorMessage()
  const canCreate = usePermission('orders.create')
  // The customer filter uses the form's customer options (orders.create or orders.update).
  const canPickCustomers = canCreate || usePermission('orders.update')

  const [searchParams, setSearchParams] = useSearchParams()
  const statusParam = searchParams.get('status') as ListStatus | null
  const status: ListStatus = statusParam && STATUSES.includes(statusParam) ? statusParam : 'all'
  const customer = searchParams.get('customer') ?? ''
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

  const filtersActive = Boolean(status !== 'all' || customer || dateFrom || dateTo || urlQ.trim())
  const clearFilters = () => {
    setQ('')
    setSearchParams({}, { replace: true })
  }

  const params = {
    status,
    customer_id: customer || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    q: urlQ.trim() || undefined,
    page,
    page_size: PAGE_SIZE,
  }
  const list = useQuery({
    queryKey: [...orderKeys.list, params],
    queryFn: async () => (await api.get<Page<OrderListItem>>('/orders', { params })).data,
    placeholderData: keepPreviousData,
  })
  const stats = useQuery({
    queryKey: orderKeys.stats,
    queryFn: async () => (await api.get<OrderStats>('/orders/stats')).data,
  })
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / PAGE_SIZE)) : 1

  const newButton = (
    <Can permission="orders.create">
      <Button onClick={() => navigate(paths.newOrder)}>
        <Icon name="plus" width={18} height={18} />
        {t('orders.new')}
      </Button>
    </Can>
  )
  const open = (item: OrderListItem) => navigate(paths.order(item.id))
  const driverName = (item: OrderListItem) =>
    item.driver ? (item.driver.is_system ? t('audit.system') : item.driver.full_name) : null

  return (
    <>
      <PageHeader
        back={paths.workstation}
        title={t('orders.title')}
        subtitle={list.data && t('common.total', { count: list.data.total })}
        actions={newButton}
      />

      <KpiGrid
        loading={stats.isPending}
        items={KPIS.map((kpi) => ({
          ...kpi,
          label: t(kpi.labelKey),
          value: stats.data?.[kpi.key],
          onClick: kpi.status ? () => update({ status: status === kpi.status ? null : kpi.status! }) : undefined,
          selected: kpi.status !== undefined && status === kpi.status,
        }))}
      />

      <div className="scrollbar-none -mx-4 mb-3 flex gap-2 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:px-0">
        {STATUSES.map((s) => (
          <Chip key={s} active={status === s} onClick={() => update({ status: s === 'all' ? null : s })}>
            {s === 'all' ? t('orders.filters.all') : t(`orders.filters.${s}`)}
          </Chip>
        ))}
      </div>

      <div className={cx('mb-4 grid gap-2', canPickCustomers ? 'xl:grid-cols-[1fr_16rem_auto]' : 'xl:grid-cols-[1fr_auto]')}>
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
            placeholder={t('orders.searchPlaceholder')}
            aria-label={t('common.search')}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        {canPickCustomers && <CustomerFilter value={customer} onChange={(id) => update({ customer: id })} />}
        <div
          role="group"
          aria-label={t('orders.filters.deliveryDate')}
          className="flex min-w-0 items-center gap-2"
        >
          <span className="shrink-0 text-sm font-medium text-stone-600">{t('orders.filters.deliveryDate')}</span>
          <Input
            type="date"
            className="min-w-0 flex-1 xl:w-40 xl:flex-none"
            aria-label={t('orders.filters.from')}
            value={dateFrom}
            max={dateTo || undefined}
            onChange={(e) => update({ from: e.target.value || null })}
          />
          <span aria-hidden className="text-stone-400">–</span>
          <Input
            type="date"
            className="min-w-0 flex-1 xl:w-40 xl:flex-none"
            aria-label={t('orders.filters.to')}
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
                <Icon name={filtersActive ? 'search' : 'receipt'} width={24} height={24} />
              </span>
              {filtersActive ? (
                <>
                  <p className="font-medium text-stone-900">{t('orders.noResults')}</p>
                  <Button variant="secondary" className="mt-4" onClick={clearFilters}>
                    {t('partners.clearFilters')}
                  </Button>
                </>
              ) : (
                <>
                  <p className="font-medium text-stone-900">{t('orders.emptyTitle')}</p>
                  <p className="mt-1 max-w-sm text-sm text-stone-500">
                    {t(canCreate ? 'orders.emptyBody' : 'orders.emptyBodyReadOnly')}
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
                      <span className="block truncate text-sm text-stone-700">{item.customer.name}</span>
                    </span>
                    <OrderStatusBadge status={item.status} />
                  </span>
                  <span className="mt-2 flex items-center justify-between gap-2 text-sm text-stone-600">
                    <span className="min-w-0 truncate">
                      {formatDay(item.delivery_date, { day: 'numeric', month: 'short' })}
                      {driverName(item) && ` · ${driverName(item)}`}
                    </span>
                    <BoxCounts white={item.white_boxes} black={item.black_boxes} />
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
                  <th className="rounded-tl-xl px-4 py-3">{t('orders.columns.code')}</th>
                  <th className="px-4 py-3">{t('orders.fields.customer')}</th>
                  <th className="whitespace-nowrap px-4 py-3">{t('orders.fields.deliveryDate')}</th>
                  <th className="px-4 py-3">{t('orders.fields.driver')}</th>
                  <th className="px-4 py-3">{t('orders.columns.boxes')}</th>
                  <th className="rounded-tr-xl px-4 py-3">{t('orders.columns.status')}</th>
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
                      <Link to={paths.order(item.id)} onClick={(e) => e.stopPropagation()} className="hover:underline">
                        {item.code}
                      </Link>
                    </td>
                    <td className="px-4 py-3">{item.customer.name}</td>
                    <td className="whitespace-nowrap px-4 py-3 tabular-nums">{formatDay(item.delivery_date)}</td>
                    <td className="px-4 py-3">{driverName(item) ?? <span className="text-stone-400">—</span>}</td>
                    <td className="px-4 py-3">
                      <BoxCounts white={item.white_boxes} black={item.black_boxes} />
                    </td>
                    <td className="px-4 py-3">
                      <OrderStatusBadge status={item.status} />
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
