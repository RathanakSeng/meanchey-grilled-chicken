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
import { useAuth } from '@/auth/AuthProvider'
import { isSuperadmin } from '@/lib/roles'
import type { AuditEntityRef, AuditLog, Page, UserRef as UserRefData } from '@/lib/types'
import { PARTNER_CONFIGS, partnerSearchLink } from '@/pages/production/partners/config'

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
  'user.role_change',
  'user.password_reset',
  'user.password_self_reset',
  'feature.set',
  'profile.update',
  ...(['supplier', 'customer'] as const).flatMap((e) =>
    ['create', 'update', 'deactivate', 'reactivate'].map((a) => `${e}.${a}`),
  ),
]
// Detailed permission entries are listed by the API for the superadmin only.
const PERMISSION_ACTIONS = ['permission.grant', 'permission.revoke']
const ENTITY_TYPES = ['supplier', 'customer'] as const
const PAGE_SIZE = 50

function actionKey(action: string) {
  return `audit.actions.${action.replace(/\./g, '_')}`
}

function UserRef({ user }: { user: UserRefData | null }) {
  const { t } = useTranslation()
  // No user, or a system reference (`is_system`): "System", never a link.
  if (!user || user.is_system || !user.id) {
    return <span className="text-stone-400">{t('audit.system')}</span>
  }
  return (
    <Link to={paths.user(user.id)} className="hover:underline" onClick={(e) => e.stopPropagation()}>
      <span className="font-medium text-stone-800">{user.full_name}</span>
      {user.telegram_username && (
        <span className="text-stone-500"> @{user.telegram_username}</span>
      )}
    </Link>
  )
}

/** The supplier / customer an entry is about, linking to its list with the name searched. */
function EntityRef({ entity }: { entity: AuditEntityRef }) {
  const { t } = useTranslation()
  const config = PARTNER_CONFIGS[entity.type as keyof typeof PARTNER_CONFIGS]
  const name = entity.name ?? t('common.none')
  return (
    <span className="block">
      <span className="block text-xs text-stone-400">{t(`audit.entityTypes.${entity.type}`, { defaultValue: entity.type })}</span>
      {config && entity.name ? (
        <Link to={partnerSearchLink(config, entity.name)} className="font-medium text-stone-800 hover:underline">
          {name}
        </Link>
      ) : (
        <span className="font-medium text-stone-800">{name}</span>
      )}
    </span>
  )
}

/** "Suppliers: View only → Full access" for a feature.set entry. */
function FeatureChange({ details }: { details: Record<string, unknown> }) {
  const { t } = useTranslation()
  const feature = String(details.feature ?? '')
  const level = (value: unknown) =>
    t(`access.levels.${String(value)}`, { defaultValue: String(value) })
  return (
    <span className="block text-sm text-stone-700">
      {t('audit.featureChange', {
        feature: t(`access.featureNames.${feature}`, { defaultValue: feature }),
        from: level(details.from),
        to: level(details.to),
      })}
    </span>
  )
}

function Details({ log }: { log: AuditLog }) {
  const { t } = useTranslation()
  const d = log.details
  if (log.action === 'feature.set') return <FeatureChange details={d} />
  if (log.action === 'user.role_change') {
    return (
      <span className="block text-sm text-stone-700">
        {t('audit.roleChange', {
          from: t(`roles.${String(d.from)}`),
          to: t(`roles.${String(d.to)}`),
        })}
      </span>
    )
  }
  const downstream = Array.isArray(d.downstream_grants)
    ? (d.downstream_grants as { full_name: string; telegram_username: string | null }[])
    : []
  const entries = Object.entries(d).filter(
    ([k]) => k !== 'downstream_grants' && !(log.entity && k === 'name'),
  )

  return (
    <div className="space-y-1">
      {typeof d.permission === 'string' && <code className="text-xs">{d.permission}</code>}
      {d.source === 'default_backfill' && (
        <span className="block text-xs text-stone-500">{t('audit.defaultBackfill')}</span>
      )}
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
  const { me } = useAuth()
  const actions =
    isSuperadmin(me?.user.role) ? [...ACTIONS, ...PERMISSION_ACTIONS] : ACTIONS
  const formatDate = useFormatDate()
  const errorMessage = useErrorMessage()
  const [action, setAction] = useState('')
  const [entityType, setEntityType] = useState('')
  const [page, setPage] = useState(1)

  const params = {
    action: action || undefined,
    entity_type: entityType || undefined,
    page,
    page_size: PAGE_SIZE,
  }
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
      <div className="mb-4 grid max-w-xl gap-2 sm:grid-cols-2">
        <Select
          aria-label={t('audit.entityType')}
          value={entityType}
          onChange={(e) => {
            setEntityType(e.target.value)
            setPage(1)
          }}
        >
          <option value="">{t('audit.allEntities')}</option>
          {ENTITY_TYPES.map((type) => (
            <option key={type} value={type}>
              {t(`audit.entityTypes.${type}`)}
            </option>
          ))}
        </Select>
        <Select
          aria-label={t('audit.action')}
          value={action}
          onChange={(e) => {
            setAction(e.target.value)
            setPage(1)
          }}
        >
          <option value="">{t('audit.allActions')}</option>
          {actions.map((a) => (
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
                  {log.entity && <EntityRef entity={log.entity} />}
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
