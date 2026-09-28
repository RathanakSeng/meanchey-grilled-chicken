import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { Can } from '@/auth/Can'
import { usePermission } from '@/auth/usePermission'
import { ActionMenu, type ActionMenuItem } from '@/components/ActionMenu'
import { Icon } from '@/components/icons'
import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  Input,
  PageHeader,
  Select,
  Spinner,
  cx,
} from '@/components/ui'
import { useIsMobileLayout } from '@/layouts/useIsMobileLayout'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useFormatDate } from '@/lib/format'
import { paths } from '@/lib/paths'
import type { Page, Partner, PartnerStats } from '@/lib/types'
import { useDebounced } from '@/lib/useDebounced'
import { partnerKeys, permission, type PartnerConfig } from './config'
import { KpiCards, type PartnerStatus } from './KpiCards'
import { PartnerFormSheet } from './PartnerFormSheet'

type Sort = 'name' | '-name' | 'created_at' | '-created_at'
const SORTS: { value: Sort; labelKey: string }[] = [
  { value: 'name', labelKey: 'partners.sort.nameAsc' },
  { value: '-name', labelKey: 'partners.sort.nameDesc' },
  { value: '-created_at', labelKey: 'partners.sort.newest' },
  { value: 'created_at', labelKey: 'partners.sort.oldest' },
]
const STATUSES: PartnerStatus[] = ['active', 'inactive', 'all']
const PAGE_SIZE = 20

function oneOf<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback
}

/**
 * List page shared by Suppliers and Customers. Filters live in the URL (?q=&status=&sort=&page=)
 * so links (e.g. from the audit log) can open a prefilled search, and Back keeps them.
 */
export function PartnerListPage({ config }: { config: PartnerConfig }) {
  const { t } = useTranslation()
  const ns = config.resource
  const keys = partnerKeys(config)
  const isMobile = useIsMobileLayout()
  const formatDate = useFormatDate()
  const errorMessage = useErrorMessage()
  const queryClient = useQueryClient()
  const canCreate = usePermission(permission(config, 'create'))
  const canUpdate = usePermission(permission(config, 'update'))
  const canDelete = usePermission(permission(config, 'delete'))

  // --- Filters (URL state) ---
  const [searchParams, setSearchParams] = useSearchParams()
  const status = oneOf(searchParams.get('status'), STATUSES, 'active')
  const sort = oneOf(
    searchParams.get('sort'),
    SORTS.map((s) => s.value),
    'name',
  )
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
        // Any filter change goes back to page 1.
        if (!('page' in changes)) next.delete('page')
        return next
      },
      { replace: true },
    )

  // Debounced search box → URL. A URL change that isn't the value we just pushed came from
  // outside (a link, Back, "Clear filters") → copy it into the search box. Comparing against
  // the debounced value, not `q`, keeps it from overwriting text that is still being typed.
  useEffect(() => {
    if (search !== urlQ.trim()) update({ q: search || null })
  }, [search])
  useEffect(() => {
    if (urlQ.trim() !== search) setQ(urlQ)
  }, [urlQ])

  const filtersActive = urlQ.trim() !== '' || status !== 'active'
  const clearFilters = () => {
    setQ('')
    setSearchParams({}, { replace: true })
  }

  // --- Data ---
  const params = {
    q: urlQ.trim() || undefined,
    status,
    sort,
    page,
    page_size: PAGE_SIZE,
  }
  const list = useQuery({
    queryKey: [...keys.list, params],
    queryFn: async () => (await api.get<Page<Partner>>(`/${config.resource}`, { params })).data,
    placeholderData: keepPreviousData,
  })
  const stats = useQuery({
    queryKey: keys.stats,
    queryFn: async () => (await api.get<PartnerStats>(`/${config.resource}/stats`)).data,
  })
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / PAGE_SIZE)) : 1
  const hasAny = stats.data ? stats.data.total_active + stats.data.inactive > 0 : true

  // --- Success message (auto-hides) ---
  const [notice, setNotice] = useState<string | null>(null)
  useEffect(() => {
    if (!notice) return
    const id = window.setTimeout(() => setNotice(null), 4000)
    return () => window.clearTimeout(id)
  }, [notice])

  // --- Create / edit sheet ---
  const [editing, setEditing] = useState<Partner | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const openCreate = () => {
    setEditing(null)
    setFormOpen(true)
  }
  const openEdit = (p: Partner) => {
    setEditing(p)
    setFormOpen(true)
  }

  // --- Deactivate / reactivate ---
  const [confirm, setConfirm] = useState<{ partner: Partner; action: 'deactivate' | 'reactivate' } | null>(
    null,
  )
  const toggle = useMutation({
    mutationFn: async ({ partner, action }: { partner: Partner; action: string }) =>
      (await api.post<Partner>(`/${config.resource}/${partner.id}/${action}`)).data,
    onSuccess: (saved, { action }) => {
      queryClient.setQueryData(keys.one(saved.id), saved)
      queryClient.invalidateQueries({ queryKey: keys.list })
      queryClient.invalidateQueries({ queryKey: keys.stats })
      setConfirm(null)
      setNotice(t(`${ns}.${action === 'deactivate' ? 'deactivated' : 'reactivated'}`, { name: saved.name }))
    },
  })
  const openConfirm = (partner: Partner, action: 'deactivate' | 'reactivate') => {
    toggle.reset()
    setConfirm({ partner, action })
  }

  const actionsFor = (p: Partner): ActionMenuItem[] => [
    ...(canUpdate
      ? [{ key: 'edit', label: t('common.edit'), icon: 'pencil' as const, onSelect: () => openEdit(p) }]
      : []),
    ...(canDelete
      ? [
          p.is_active
            ? {
                key: 'deactivate',
                label: t('partners.deactivate'),
                icon: 'archive' as const,
                tone: 'danger' as const,
                onSelect: () => openConfirm(p, 'deactivate'),
              }
            : {
                key: 'reactivate',
                label: t('partners.reactivate'),
                icon: 'restore' as const,
                onSelect: () => openConfirm(p, 'reactivate'),
              },
        ]
      : []),
  ]

  const newButton = (
    <Can permission={permission(config, 'create')}>
      <Button onClick={openCreate}>
        <Icon name="plus" width={18} height={18} />
        {t(`${ns}.new`)}
      </Button>
    </Can>
  )

  return (
    <>
      <PageHeader
        back={paths.production}
        title={t(`${ns}.title`)}
        subtitle={list.data && t('common.total', { count: list.data.total })}
        actions={newButton}
      />

      <KpiCards
        stats={stats.data}
        loading={stats.isPending}
        status={status}
        onStatus={(s) => update({ status: s === 'active' ? null : s })}
      />

      <div className="mb-4 grid gap-2 sm:grid-cols-[1fr_auto_auto]">
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
            placeholder={t(`${ns}.searchPlaceholder`)}
            aria-label={t('common.search')}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div className="grid grid-cols-2 gap-2 sm:contents">
          <Select
            aria-label={t('partners.filterStatus')}
            value={status}
            onChange={(e) => update({ status: e.target.value === 'active' ? null : e.target.value })}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`partners.status.${s}`)}
              </option>
            ))}
          </Select>
          <Select
            aria-label={t('partners.sort.label')}
            value={sort}
            onChange={(e) => update({ sort: e.target.value === 'name' ? null : e.target.value })}
          >
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {t(s.labelKey)}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {notice && (
        <Alert tone="success" className="mb-4">
          {notice}
        </Alert>
      )}
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
                <Icon name={hasAny ? 'search' : config.icon} width={24} height={24} />
              </span>
              {!hasAny && !filtersActive ? (
                <>
                  <p className="font-medium text-stone-900">{t(`${ns}.emptyTitle`)}</p>
                  <p className="mt-1 max-w-sm text-sm text-stone-500">
                    {t(canCreate ? `${ns}.emptyBody` : `${ns}.emptyBodyReadOnly`)}
                  </p>
                  {canCreate && <div className="mt-4">{newButton}</div>}
                </>
              ) : filtersActive ? (
                <>
                  <p className="font-medium text-stone-900">{t('partners.noResults')}</p>
                  <Button variant="secondary" className="mt-4" onClick={clearFilters}>
                    {t('partners.clearFilters')}
                  </Button>
                </>
              ) : (
                <>
                  <p className="font-medium text-stone-900">{t(`${ns}.noActive`)}</p>
                  <Button
                    variant="secondary"
                    className="mt-4"
                    onClick={() => update({ status: 'inactive' })}
                  >
                    {t('partners.showDeactivated')}
                  </Button>
                </>
              )}
            </div>
          </Card>
        ) : isMobile ? (
          <ul className={cx('space-y-2', list.isPlaceholderData && 'opacity-60')}>
            {list.data.items.map((p) => (
              <li
                key={p.id}
                className={cx(
                  'rounded-xl bg-white p-3 shadow-sm ring-1 ring-stone-200',
                  !p.is_active && 'opacity-60',
                )}
              >
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-center gap-2 font-medium text-stone-900">
                      <span className="break-words">{p.name}</span>
                      {!p.is_active && <Badge>{t('partners.deactivatedBadge')}</Badge>}
                    </p>
                    {p.location && (
                      <p className="mt-0.5 flex items-center gap-1 text-sm text-stone-500">
                        <Icon name="mapPin" width={14} height={14} className="shrink-0" />
                        <span className="truncate">{p.location}</span>
                      </p>
                    )}
                    {p.phone_display && (
                      <p className="mt-0.5 text-sm tabular-nums text-stone-600">{p.phone_display}</p>
                    )}
                  </div>
                  <ActionMenu items={actionsFor(p)} label={t('partners.actions')} />
                </div>
                {p.phone && (
                  <a
                    href={`tel:${p.phone}`}
                    className="mt-3 flex items-center justify-center gap-2 rounded-lg bg-green-600 px-4 py-2.5 text-sm font-semibold text-white active:bg-green-700"
                  >
                    <Icon name="phone" width={18} height={18} />
                    {t('partners.call')}
                  </a>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <div
            className={cx(
              'rounded-xl bg-white shadow-sm ring-1 ring-stone-200',
              list.isPlaceholderData && 'opacity-60',
            )}
          >
            <table className="min-w-full divide-y divide-stone-200 text-sm">
              <thead className="bg-stone-50 text-left text-xs font-semibold uppercase tracking-wide text-stone-500">
                <tr>
                  <th className="rounded-tl-xl px-4 py-3">{t('partners.fields.name')}</th>
                  <th className="px-4 py-3">{t('partners.fields.location')}</th>
                  <th className="px-4 py-3">{t('partners.fields.phone')}</th>
                  <th className="px-4 py-3">{t('partners.columns.added')}</th>
                  <th className="px-4 py-3">{t('partners.columns.status')}</th>
                  <th className="w-12 rounded-tr-xl px-2 py-3">
                    <span className="sr-only">{t('partners.actions')}</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {list.data.items.map((p) => (
                  <tr key={p.id} className={cx('hover:bg-stone-50/60', !p.is_active && 'text-stone-400')}>
                    <td className={cx('px-4 py-3 font-medium', p.is_active ? 'text-stone-900' : 'text-stone-500')}>
                      {p.name}
                    </td>
                    <td className="px-4 py-3">{p.location ?? t('common.none')}</td>
                    <td className="whitespace-nowrap px-4 py-3 tabular-nums">
                      {p.phone ? (
                        <a href={`tel:${p.phone}`} className="text-brand-700 hover:underline">
                          {p.phone_display}
                        </a>
                      ) : (
                        t('common.none')
                      )}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      {formatDate(p.created_at, { dateStyle: 'medium' })}
                    </td>
                    <td className="px-4 py-3">
                      {p.is_active ? (
                        <Badge tone="green">{t('status.active')}</Badge>
                      ) : (
                        <Badge>{t('partners.deactivatedBadge')}</Badge>
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      <ActionMenu items={actionsFor(p)} label={t('partners.actions')} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}

      {list.data && pages > 1 && (
        <div className="mt-4 flex items-center justify-between gap-2 text-sm text-stone-600">
          <Button
            variant="secondary"
            disabled={page <= 1}
            onClick={() => update({ page: String(page - 1) })}
          >
            {t('common.previous')}
          </Button>
          <span>{t('common.pageOf', { page, pages })}</span>
          <Button
            variant="secondary"
            disabled={page >= pages}
            onClick={() => update({ page: String(page + 1) })}
          >
            {t('common.next')}
          </Button>
        </div>
      )}

      <PartnerFormSheet
        config={config}
        open={formOpen}
        partner={editing}
        onClose={() => setFormOpen(false)}
        onSaved={(saved, created) => {
          setFormOpen(false)
          setNotice(t(`${ns}.${created ? 'created' : 'updated'}`, { name: saved.name }))
        }}
      />

      <ConfirmDialog
        open={confirm !== null}
        title={confirm ? t(`${ns}.${confirm.action}Title`) : ''}
        body={confirm ? t(`${ns}.${confirm.action}Body`, { name: confirm.partner.name }) : null}
        confirmLabel={
          confirm?.action === 'deactivate' ? t('partners.deactivate') : t('partners.reactivate')
        }
        tone={confirm?.action === 'deactivate' ? 'danger' : 'primary'}
        loading={toggle.isPending}
        error={toggle.isError ? errorMessage(toggle.error) : null}
        onConfirm={() => confirm && toggle.mutate(confirm)}
        onClose={() => setConfirm(null)}
      />
    </>
  )
}
