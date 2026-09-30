import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '@/auth/AuthProvider'
import { Can } from '@/auth/Can'
import { RoleBadge, UserStatusBadges } from '@/components/badges'
import { Icon } from '@/components/icons'
import { Alert, Button, Card, EmptyState, Input, PageHeader, Select, Spinner } from '@/components/ui'
import { Avatar } from '@/components/ProfileMenu'
import { useIsMobileLayout } from '@/layouts/useIsMobileLayout'
import { api } from '@/lib/api'
import { paths } from '@/lib/paths'
import { useErrorMessage } from '@/lib/errors'
import type { Page, Role, User } from '@/lib/types'
import { useDebounced } from '@/lib/useDebounced'
import { usePositions } from '@/lib/usePositions'
import { useRoleCapacity } from '@/lib/useRoleCapacity'

type Status = 'active' | 'inactive' | 'all'
const PAGE_SIZE = 20

export function UsersListPage() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const navigate = useNavigate()
  const errorMessage = useErrorMessage()
  const isMobile = useIsMobileLayout()

  const [q, setQ] = useState('')
  const [role, setRole] = useState<Role | ''>('')
  const [position, setPosition] = useState('')
  const positions = usePositions()
  const [status, setStatus] = useState<Status>('active')
  const [page, setPage] = useState(1)
  const search = useDebounced(q.trim())
  const capacity = useRoleCapacity()

  const params = {
    q: search || undefined,
    role: role || undefined,
    position: position || undefined,
    status,
    page,
    page_size: PAGE_SIZE,
  }
  const query = useQuery({
    queryKey: ['users', params],
    queryFn: async () => (await api.get<Page<User>>('/users', { params })).data,
    placeholderData: keepPreviousData,
  })

  const resetPage = <T,>(setter: (v: T) => void) => (v: T) => {
    setter(v)
    setPage(1)
  }
  const pages = query.data ? Math.max(1, Math.ceil(query.data.total / PAGE_SIZE)) : 1
  // Only staff have a position, so the filter only makes sense when staff are in scope.
  const staffInScope = me?.manageable_roles.includes('staff') ?? false
  const showPosition = staffInScope && (role === '' || role === 'staff')

  return (
    <>
      <PageHeader
        back={paths.settings}
        title={t('users.title')}
        subtitle={
          <>
            {query.data && t('common.total', { count: query.data.total })}
            {capacity.data && capacity.data.length > 0 && (
              <span className="mt-0.5 flex flex-wrap gap-x-2 text-xs tabular-nums">
                {capacity.data.map((c, i) => (
                  <span key={c.role} className="whitespace-nowrap">
                    {i > 0 && <span aria-hidden>· </span>}
                    {t('roleCapacity.line', {
                      roles: t(`userLimits.pluralTitle.${c.role}`),
                      count: c.active,
                      limit: c.limit ?? t('roleCapacity.noLimit'),
                    })}
                  </span>
                ))}
              </span>
            )}
          </>
        }
        actions={
          <Can permission="users.create">
            <Button onClick={() => navigate(paths.newUser)}>
              <Icon name="plus" width={18} height={18} />
              {t('users.new')}
            </Button>
          </Can>
        }
      />

      <div className="mb-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <div className="relative sm:col-span-2 lg:col-span-1">
          <Icon
            name="search"
            width={16}
            height={16}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-400"
          />
          <Input
            className="pl-9"
            placeholder={t('users.searchPlaceholder')}
            aria-label={t('common.search')}
            value={q}
            onChange={(e) => resetPage(setQ)(e.target.value)}
          />
        </div>
        <Select
          aria-label={t('users.filterRole')}
          value={role}
          onChange={(e) => {
            resetPage(setRole)(e.target.value as Role | '')
            if (e.target.value !== 'staff') setPosition('')
          }}
        >
          <option value="">
            {t('users.filterRole')}: {t('common.all')}
          </option>
          {me?.manageable_roles.map((r) => (
            <option key={r} value={r}>
              {t(`roles.${r}`)}
            </option>
          ))}
        </Select>
        {showPosition && (
          <Select
            aria-label={t('users.filterPosition')}
            value={position}
            onChange={(e) => resetPage(setPosition)(e.target.value)}
          >
            <option value="">
              {t('users.filterPosition')}: {t('common.all')}
            </option>
            {positions.data?.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </Select>
        )}
        <Select
          aria-label={t('users.filterStatus')}
          value={status}
          onChange={(e) => resetPage(setStatus)(e.target.value as Status)}
        >
          <option value="active">{t('status.active')}</option>
          <option value="inactive">{t('status.inactive')}</option>
          <option value="all">
            {t('users.filterStatus')}: {t('users.statusAll')}
          </option>
        </Select>
      </div>

      {query.isError && <Alert tone="error">{errorMessage(query.error)}</Alert>}
      {query.isPending && (
        <div className="flex justify-center py-10 text-brand-600">
          <Spinner />
        </div>
      )}

      {query.data &&
        (query.data.items.length === 0 ? (
          <Card>
            <EmptyState>{t('users.empty')}</EmptyState>
          </Card>
        ) : isMobile ? (
          <ul className="space-y-2">
            {query.data.items.map((u) => (
              <li key={u.id}>
                <Link
                  to={paths.user(u.id)}
                  className="flex items-center gap-3 rounded-xl bg-white p-3 shadow-sm ring-1 ring-stone-200"
                >
                  <Avatar name={u.full_name} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-stone-900">{u.full_name}</p>
                    <p className="truncate text-xs text-stone-500">@{u.telegram_username}</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      <RoleBadge role={u.role} position={u.position} />
                      <UserStatusBadges user={u} />
                    </div>
                  </div>
                  <Icon name="chevronRight" className="text-stone-400" />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <div className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-stone-200">
            <table className="min-w-full divide-y divide-stone-200 text-sm">
              <thead className="bg-stone-50 text-left text-xs font-semibold uppercase tracking-wide text-stone-500">
                <tr>
                  <th className="px-4 py-3">{t('users.columns.name')}</th>
                  <th className="px-4 py-3">{t('users.columns.telegram')}</th>
                  <th className="px-4 py-3">{t('users.columns.role')}</th>
                  <th className="px-4 py-3">{t('users.columns.phone')}</th>
                  <th className="px-4 py-3">{t('users.columns.status')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {query.data.items.map((u) => (
                  <tr
                    key={u.id}
                    onClick={() => navigate(paths.user(u.id))}
                    className="cursor-pointer hover:bg-brand-50/40"
                  >
                    <td className="px-4 py-3">
                      <Link to={paths.user(u.id)} className="flex items-center gap-3">
                        <Avatar name={u.full_name} className="h-8 w-8 text-xs" />
                        <span className="font-medium text-stone-900">{u.full_name}</span>
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-stone-600">@{u.telegram_username}</td>
                    <td className="px-4 py-3">
                      <RoleBadge role={u.role} position={u.position} />
                    </td>
                    <td className="px-4 py-3 text-stone-600">{u.phone ?? t('common.none')}</td>
                    <td className="px-4 py-3">
                      <UserStatusBadges user={u} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}

      {query.data && pages > 1 && (
        <div className="mt-4 flex items-center justify-between gap-2 text-sm text-stone-600">
          <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            {t('common.previous')}
          </Button>
          <span>{t('common.pageOf', { page, pages })}</span>
          <Button
            variant="secondary"
            disabled={page >= pages}
            onClick={() => setPage((p) => p + 1)}
          >
            {t('common.next')}
          </Button>
        </div>
      )}
    </>
  )
}
