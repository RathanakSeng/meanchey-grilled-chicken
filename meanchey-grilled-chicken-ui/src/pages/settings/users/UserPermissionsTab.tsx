import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { usePermission } from '@/auth/usePermission'
import { Icon } from '@/components/icons'
import { Alert, Card, EmptyState, Spinner, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useLocalized } from '@/lib/format'
import type { UserPermission, UserPermissions } from '@/lib/types'

export function UserPermissionsTab({ userId }: { userId: string }) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const errorMessage = useErrorMessage()
  const queryClient = useQueryClient()
  const canGrant = usePermission('permissions.grant')
  const queryKey = ['user-permissions', userId]

  const query = useQuery({
    queryKey,
    queryFn: async () => (await api.get<UserPermissions>(`/users/${userId}/permissions`)).data,
  })

  const toggle = useMutation({
    mutationFn: async (p: UserPermission) => {
      const url = `/users/${userId}/permissions/${encodeURIComponent(p.code)}`
      if (p.granted) await api.delete(url)
      else await api.put(url)
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey }),
  })

  if (query.isPending) {
    return (
      <div className="flex justify-center py-10 text-brand-600">
        <Spinner />
      </div>
    )
  }
  if (query.isError) return <Alert tone="error">{errorMessage(query.error)}</Alert>

  const modules = query.data.modules
  if (modules.length === 0) {
    return (
      <Card>
        <EmptyState>{t('permissions.noneAssignable')}</EmptyState>
      </Card>
    )
  }

  const anyEditable = modules.some((m) => m.permissions.some((p) => p.can_edit))
  // Why a checkbox is locked, from the API's `reason` (an error code) → errors.<CODE>.
  const lockReason = (p: UserPermission) =>
    p.can_edit
      ? undefined
      : p.reason
        ? t(`errors.${p.reason}`, { defaultValue: t('permissions.notEditable') })
        : t('permissions.notEditable')
  // Reasons specific to one item are shown inline too (tooltips don't exist on touch screens);
  // the others (no grant permission, out of scope, user deactivated) apply to every item, so
  // the notice above the list states them once.
  const INLINE_REASONS = ['PERMISSION_GRANT_RESTRICTED', 'PERMISSION_NOT_HELD']
  const tabReason = modules
    .flatMap((m) => m.permissions)
    .map((p) => p.reason)
    .find((r) => r && !INLINE_REASONS.includes(r))

  return (
    <div className="space-y-4">
      {(!canGrant || !anyEditable) && (
        <Alert tone="info">
          {t('permissions.readOnlyNotice')}
          {tabReason && ` ${t(`errors.${tabReason}`, { defaultValue: '' })}`}
        </Alert>
      )}
      {toggle.isError && <Alert tone="error">{errorMessage(toggle.error)}</Alert>}
      {modules.map((m) => (
        <Card key={m.module} title={localized(m)}>
          <ul className="-my-2 divide-y divide-stone-100">
            {m.permissions.map((p) => {
              const busy = toggle.isPending && toggle.variables?.code === p.code
              return (
                <li key={p.code} className="py-2">
                  <label
                    className={cx(
                      'flex items-start gap-3 rounded-lg p-2',
                      p.can_edit ? 'cursor-pointer hover:bg-stone-50' : 'cursor-not-allowed',
                    )}
                    title={lockReason(p)}
                  >
                    <input
                      type="checkbox"
                      className="mt-1 h-4 w-4 rounded border-stone-300 text-brand-600 focus:ring-brand-500 disabled:opacity-50"
                      checked={p.granted}
                      disabled={!p.can_edit || toggle.isPending}
                      onChange={() => toggle.mutate(p)}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span
                          className={cx(
                            'text-sm font-medium',
                            p.can_edit ? 'text-stone-900' : 'text-stone-500',
                          )}
                        >
                          {localized(p)}
                        </span>
                        {busy && <Spinner className="h-3.5 w-3.5 text-brand-600" />}
                      </span>
                      <span className="block text-xs text-stone-500">
                        {localized(p, 'description')}
                      </span>
                      <code className="text-[11px] text-stone-400">{p.code}</code>
                      {!p.can_edit && p.reason && INLINE_REASONS.includes(p.reason) && (
                        <span className="mt-1 flex items-center gap-1 text-xs text-amber-700">
                          <Icon name="lock" width={12} height={12} className="shrink-0" />
                          {lockReason(p)}
                        </span>
                      )}
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
        </Card>
      ))}
    </div>
  )
}
