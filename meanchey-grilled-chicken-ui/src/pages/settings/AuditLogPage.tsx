import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Alert, Badge, Button, Card, EmptyState, PageHeader, Select, Spinner } from '@/components/ui'
import { Icon } from '@/components/icons'
import { api } from '@/lib/api'
import { paths } from '@/lib/paths'
import { useErrorMessage } from '@/lib/errors'
import { useFormatDate } from '@/lib/format'
import type { AuditLog, AuditUserRef, Page } from '@/lib/types'

const ACTIONS = [
  'auth.login',
  'auth.login_failed',
  'auth.locked',
  'auth.logout',
  'auth.password_changed',
  'auth.telegram_bound',
  'user.create',
  'user.update',
  'user.deactivate',
  'user.reactivate',
  'user.password_reset',
  'user.password_self_reset',
  'permission.grant',
  'permission.revoke',
  'profile.update',
]
const PAGE_SIZE = 50

function actionKey(action: string) {
  return `audit.actions.${action.replace(/\./g, '_')}`
}

function UserRef({ user }: { user: AuditUserRef | null }) {
  const { t } = useTranslation()
  if (!user) return <span className="text-stone-400">{t('audit.system')}</span>
  return (
    <Link to={paths.user(user.id)} className="hover:underline" onClick={(e) => e.stopPropagation()}>
      <span className="font-medium text-stone-800">{user.full_name}</span>
      {user.telegram_username && (
        <span className="text-stone-500"> @{user.telegram_username}</span>
      )}
    </Link>
  )
}

function Details({ log }: { log: AuditLog }) {
  const { t } = useTranslation()
  const d = log.details
  const downstream = Array.isArray(d.downstream_grants)
    ? (d.downstream_grants as { full_name: string; telegram_username: string | null }[])
    : []
  const entries = Object.entries(d).filter(([k]) => k !== 'downstream_grants')

  return (
    <div className="space-y-1">
      {typeof d.permission === 'string' && <code className="text-xs">{d.permission}</code>}
      {downstream.length > 0 && (
        <div className="rounded-md bg-amber-50 p-2 text-xs text-amber-900 ring-1 ring-amber-200">
          <p className="flex items-center gap-1 font-medium">
            <Icon name="alert" width={14} height={14} />
            {t('audit.downstreamWarning', { count: downstream.length })}
          </p>
          <p className="mt-0.5">
            {downstream.map((g) => g.full_name + (g.telegram_username ? ` (@${g.telegram_username})` : '')).join(', ')}
          </p>
        </div>
      )}
      {entries.length > 0 && typeof d.permission !== 'string' && (
        <details className="text-xs text-stone-500">
          <summary className="cursor-pointer select-none">{t('audit.details')}</summary>
          <pre className="mt-1 max-w-md overflow-x-auto whitespace-pre-wrap break-all rounded bg-stone-50 p-2">
            {JSON.stringify(Object.fromEntries(entries), null, 2)}
          </pre>
        </details>
      )}
    </div>
  )
}

export function AuditLogPage() {
  const { t } = useTranslation()
  const formatDate = useFormatDate()
  const errorMessage = useErrorMessage()
  const [action, setAction] = useState('')
  const [page, setPage] = useState(1)

  const params = { action: action || undefined, page, page_size: PAGE_SIZE }
  const query = useQuery({
    queryKey: ['audit-logs', params],
    queryFn: async () => (await api.get<Page<AuditLog>>('/audit-logs', { params })).data,
    placeholderData: keepPreviousData,
  })
  const pages = query.data ? Math.max(1, Math.ceil(query.data.total / PAGE_SIZE)) : 1

  return (
    <>
      <PageHeader
        back={paths.settings}
        title={t('audit.title')}
        subtitle={query.data && t('common.total', { count: query.data.total })}
      />
      <div className="mb-4 max-w-xs">
        <Select
          aria-label={t('audit.action')}
          value={action}
          onChange={(e) => {
            setAction(e.target.value)
            setPage(1)
          }}
        >
          <option value="">{t('audit.allActions')}</option>
          {ACTIONS.map((a) => (
            <option key={a} value={a}>
              {t(actionKey(a))}
            </option>
          ))}
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
            <EmptyState>{t('audit.empty')}</EmptyState>
          </Card>
        ) : (
          <ul className="space-y-2">
            {query.data.items.map((log) => (
              <li
                key={log.id}
                className="grid gap-2 rounded-xl bg-white p-3 text-sm shadow-sm ring-1 ring-stone-200 sm:grid-cols-[10rem_12rem_1fr_1fr] sm:items-start sm:gap-4 sm:p-4"
              >
                <span className="text-xs text-stone-500">{formatDate(log.created_at)}</span>
                <span>
                  <Badge tone={log.action.includes('failed') || log.action.includes('locked') ? 'red' : 'neutral'}>
                    {t(actionKey(log.action), { defaultValue: log.action })}
                  </Badge>
                </span>
                <span className="min-w-0 space-y-0.5">
                  <span className="block text-xs text-stone-400">{t('audit.actor')}</span>
                  <UserRef user={log.actor} />
                </span>
                <span className="min-w-0 space-y-1">
                  {log.target && (
                    <>
                      <span className="block text-xs text-stone-400">{t('audit.target')}</span>
                      <UserRef user={log.target} />
                    </>
                  )}
                  <Details log={log} />
                </span>
              </li>
            ))}
          </ul>
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
