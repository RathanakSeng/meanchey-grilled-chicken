import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useAuth } from '@/auth/AuthProvider'
import { Can } from '@/auth/Can'
import { usePermission } from '@/auth/usePermission'
import { isLocked, RoleBadge, UserStatusBadges } from '@/components/badges'
import { Icon } from '@/components/icons'
import { Avatar } from '@/components/ProfileMenu'
import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  FullScreenSpinner,
  PageHeader,
  cx,
} from '@/components/ui'
import { api } from '@/lib/api'
import { paths } from '@/lib/paths'
import { useErrorMessage } from '@/lib/errors'
import { useFormatDate } from '@/lib/format'
import { isSuperadmin } from '@/lib/roles'
import type { User, UserFeatures } from '@/lib/types'
import { invalidateRoleCapacity } from '@/lib/useRoleCapacity'
import { RoleChangeSheet } from './RoleChangeSheet'
import { UserAccessTab, userFeaturesKey } from './UserAccessTab'
import { UserPermissionsTab } from './UserPermissionsTab'

type Action = 'reset' | 'deactivate' | 'reactivate'
type Tab = 'info' | 'access' | 'permissions'

export function UserDetailPage() {
  const { id = '' } = useParams()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const formatDate = useFormatDate()
  const { me } = useAuth()
  const createdUsername = (location.state as { created?: string } | null)?.created

  const [pending, setPending] = useState<Action | null>(null)
  const [roleSheet, setRoleSheet] = useState(false)
  const canUpdate = usePermission('users.update')
  const [notice, setNotice] = useState<string | null>(null)

  const query = useQuery({
    queryKey: ['user', id],
    queryFn: async () => (await api.get<User>(`/users/${id}`)).data,
  })
  // Access levels: only for viewers who manage features, and only shown when some apply.
  const features = useQuery({
    queryKey: userFeaturesKey(id),
    queryFn: async () => (await api.get<UserFeatures>(`/users/${id}/features`)).data,
    enabled: Boolean(me?.can_manage_features),
  })

  // Details for everyone; Access with can_manage_features; Permissions (advanced) only for the
  // superadmin.
  const tabs: Tab[] = [
    'info',
    ...(features.data && features.data.menus.length > 0 ? (['access'] as const) : []),
    ...(isSuperadmin(me?.user.role) ? (['permissions'] as const) : []),
  ]
  const requested = searchParams.get('tab') as Tab | null
  // An unknown or unavailable ?tab= falls back to Details.
  const tab: Tab = requested && tabs.includes(requested) ? requested : 'info'

  const action = useMutation({
    mutationFn: async (a: Action) => {
      if (a === 'reset') await api.post(`/users/${id}/reset-password`)
      else return (await api.post<User>(`/users/${id}/${a}`)).data
    },
    onSuccess: (user, a) => {
      if (user) queryClient.setQueryData(['user', id], user)
      else void queryClient.invalidateQueries({ queryKey: ['user', id] })
      void queryClient.invalidateQueries({ queryKey: ['users'] })
      invalidateRoleCapacity(queryClient)
      void queryClient.invalidateQueries({ queryKey: ['user-permissions', id] })
      void queryClient.invalidateQueries({ queryKey: userFeaturesKey(id) })
      setNotice(
        t(
          a === 'reset'
            ? 'userDetail.resetDone'
            : a === 'deactivate'
              ? 'userDetail.deactivated'
              : 'userDetail.reactivated',
        ),
      )
      setPending(null)
    },
  })

  if (query.isPending) return <FullScreenSpinner />
  if (query.isError) {
    return (
      <>
        <PageHeader title={t('users.title')} back={paths.users} />
        <Alert tone="error">{errorMessage(query.error)}</Alert>
      </>
    )
  }

  const user = query.data
  // Promote / demote: to any other role the viewer manages (GM: supervisor <-> staff).
  const roleOptions = (me?.manageable_roles ?? []).filter((r) => r !== user.role)
  const canChangeRole =
    canUpdate && roleOptions.length > 0 && (me?.manageable_roles ?? []).includes(user.role)
  const dialog: Record<Action, { title: string; body: string; label: string }> = {
    reset: {
      title: t('userDetail.confirmResetTitle'),
      body: t('userDetail.confirmResetBody', {
        name: user.full_name,
        username: user.telegram_username,
      }),
      label: t('userDetail.resetPassword'),
    },
    deactivate: {
      title: t('userDetail.confirmDeactivateTitle'),
      body: t('userDetail.confirmDeactivateBody', { name: user.full_name }),
      label: t('userDetail.deactivate'),
    },
    reactivate: {
      title: t('userDetail.confirmReactivateTitle'),
      body: t('userDetail.confirmReactivateBody', { name: user.full_name }),
      label: t('userDetail.reactivate'),
    },
  }

  return (
    <>
      <PageHeader
        back={paths.users}
        title={
          <span className="flex items-center gap-3">
            <Avatar name={user.full_name} />
            <span className="truncate">{user.full_name}</span>
          </span>
        }
        subtitle={
          <span className="flex flex-wrap items-center gap-1.5">
            <span>@{user.telegram_username}</span>
            <RoleBadge role={user.role} position={user.position} />
            <UserStatusBadges user={user} />
          </span>
        }
        actions={
          <>
            <Can permission="users.update">
              <Button variant="secondary" onClick={() => navigate(paths.editUser(id))}>
                {t('common.edit')}
              </Button>
            </Can>
            {canChangeRole && (
              <Button variant="secondary" onClick={() => setRoleSheet(true)}>
                <Icon name="users" width={16} height={16} />
                {t('roleChange.button')}
              </Button>
            )}
            {user.is_active && (
              <Can permission="users.reset_password">
                <Button variant="secondary" onClick={() => setPending('reset')}>
                  <Icon name="key" width={16} height={16} />
                  {t('userDetail.resetPassword')}
                </Button>
              </Can>
            )}
            <Can permission="users.delete">
              {user.is_active ? (
                <Button variant="danger" onClick={() => setPending('deactivate')}>
                  {t('userDetail.deactivate')}
                </Button>
              ) : (
                <Button onClick={() => setPending('reactivate')}>{t('userDetail.reactivate')}</Button>
              )}
            </Can>
          </>
        }
      />

      {createdUsername && !notice && (
        <Alert tone="success" className="mb-4">
          {t('userDetail.createdSuccess', { username: createdUsername })}
        </Alert>
      )}
      {notice && (
        <Alert tone="success" className="mb-4">
          {notice}
        </Alert>
      )}

      <div className="mb-4 flex gap-1 border-b border-stone-200">
        {tabs.map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setSearchParams(key === 'info' ? {} : { tab: key }, { replace: true })}
            className={cx(
              '-mb-px border-b-2 px-4 py-2 text-sm font-medium',
              tab === key
                ? 'border-brand-600 text-brand-700'
                : 'border-transparent text-stone-500 hover:text-stone-800',
            )}
          >
            {t(`userDetail.tabs.${key}`)}
          </button>
        ))}
      </div>

      {tab === 'info' ? (
        <Card>
          <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
            <Item label={t('userForm.fullName')}>{user.full_name}</Item>
            <Item label={t('userForm.telegramUsername')}>
              <span className="flex flex-wrap items-center gap-2">
                @{user.telegram_username}
                <Badge tone={user.telegram_linked ? 'blue' : 'neutral'}>
                  {t(user.telegram_linked ? 'status.telegramLinked' : 'status.telegramNotLinked')}
                </Badge>
              </span>
            </Item>
            <Item label={t('userForm.role')}>{t(`roles.${user.role}`)}</Item>
            {user.position && (
              <Item label={t('userForm.position')}>{user.position}</Item>
            )}
            <Item label={t('userForm.phone')}>{user.phone ?? t('common.none')}</Item>
            <Item label={t('userForm.language')}>{t(`languages.${user.language}`)}</Item>
            <Item label={t('userDetail.createdAt')}>{formatDate(user.created_at)}</Item>
            <Item label={t('userDetail.updatedAt')}>{formatDate(user.updated_at)}</Item>
            {user.deleted_at && (
              <Item label={t('userDetail.deactivatedAt')}>{formatDate(user.deleted_at)}</Item>
            )}
            {isLocked(user) && (
              <Item label={t('userDetail.lockedUntil')}>{formatDate(user.locked_until)}</Item>
            )}
          </dl>
        </Card>
      ) : tab === 'access' && features.data ? (
        <UserAccessTab userId={user.id} data={features.data} targetRole={user.role} />
      ) : tab === 'permissions' ? (
        <UserPermissionsTab userId={user.id} />
      ) : null}

      {canChangeRole && (
        <RoleChangeSheet
          user={user}
          roles={roleOptions}
          open={roleSheet}
          onClose={() => setRoleSheet(false)}
          onChanged={(updated) => {
            setRoleSheet(false)
            setNotice(t('roleChange.done', { name: updated.full_name, role: t(`roles.${updated.role}`) }))
          }}
        />
      )}

      {pending && (
        <ConfirmDialog
          open
          title={dialog[pending].title}
          body={dialog[pending].body}
          confirmLabel={dialog[pending].label}
          tone={pending === 'reactivate' ? 'primary' : 'danger'}
          loading={action.isPending}
          error={action.isError ? errorMessage(action.error) : null}
          onConfirm={() => action.mutate(pending)}
          onClose={() => {
            setPending(null)
            action.reset()
          }}
        />
      )}
    </>
  )
}

function Item({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-stone-500">{label}</dt>
      <dd className="mt-1 text-sm text-stone-900">{children}</dd>
    </div>
  )
}
