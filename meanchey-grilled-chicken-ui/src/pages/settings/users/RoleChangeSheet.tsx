import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Sheet } from '@/components/Sheet'
import { Alert, Button, Field, Input, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { ClientError, getError, useErrorMessage } from '@/lib/errors'
import { normalizePosition, POSITIONS_QUERY_KEY, usePositions } from '@/lib/usePositions'
import { POSITION_MAX_LENGTH, type Role, type User } from '@/lib/types'
import { invalidateRoleCapacity, useRoleCapacity } from '@/lib/useRoleCapacity'
import { userFeaturesKey } from './UserAccessTab'

interface Props {
  user: User
  /** Roles the viewer may move this user to (manageable roles minus the current one). */
  roles: Role[]
  open: boolean
  onClose(): void
  onChanged(user: User): void
}

/**
 * Promote / demote. The new role's default access replaces the old one (the API does this), so
 * the sheet says so; staff need a position.
 */
export function RoleChangeSheet({ user, roles, open, onClose, onChanged }: Props) {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const queryClient = useQueryClient()
  const positions = usePositions()
  const [role, setRole] = useState<Role | null>(null)
  const [position, setPosition] = useState('')
  const [error, setError] = useState<unknown>(null)
  const capacity = useRoleCapacity()
  // An inactive user takes no slot, so only an active one is limited by the new role's capacity.
  const isFull = (r: Role) => user.is_active && (capacity.byRole(r)?.full ?? false)

  useEffect(() => {
    if (!open) return
    setRole(roles.find((r) => !isFull(r)) ?? null)
    setPosition('')
    setError(null)
  }, [open, roles, capacity.data])

  const change = useMutation({
    mutationFn: async (body: { role: Role; position?: string }) =>
      (await api.post<User>(`/users/${user.id}/role`, body)).data,
    onSuccess: (updated) => {
      queryClient.setQueryData(['user', user.id], updated)
      void queryClient.invalidateQueries({ queryKey: ['users'] })
      void queryClient.invalidateQueries({ queryKey: userFeaturesKey(user.id) })
      void queryClient.invalidateQueries({ queryKey: ['user-permissions', user.id] })
      void queryClient.invalidateQueries({ queryKey: POSITIONS_QUERY_KEY })
      invalidateRoleCapacity(queryClient)
      onChanged(updated)
    },
    onError: setError,
  })

  const needsPosition = role === 'staff'
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!role) return
    const value = normalizePosition(position)
    if (needsPosition && !value) {
      setError(new ClientError('POSITION_REQUIRED'))
      return
    }
    change.mutate(needsPosition ? { role, position: value } : { role })
  }

  const positionError = error && getError(error).code.startsWith('POSITION') ? error : null
  const formError = error && !positionError ? error : null

  return (
    <Sheet
      open={open}
      onClose={onClose}
      busy={change.isPending}
      title={t('roleChange.title', { name: user.full_name })}
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose} disabled={change.isPending}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" form="role-change-form" loading={change.isPending} disabled={!role}>
            {t('roleChange.submit')}
          </Button>
        </div>
      }
    >
      <form id="role-change-form" onSubmit={onSubmit} noValidate className="space-y-4">
        <p className="text-sm text-stone-600">
          {t('roleChange.current', { role: t(`roles.${user.role}`) })}
        </p>
        {formError != null && <Alert tone="error">{errorMessage(formError)}</Alert>}

        <fieldset>
          <legend className="mb-2 text-sm font-medium text-stone-700">{t('roleChange.newRole')}</legend>
          <div className="grid gap-2">
            {roles.map((r) => {
              const full = isFull(r)
              const c = capacity.byRole(r)
              return (
                <label
                  key={r}
                  className={cx(
                    'flex min-h-11 items-center gap-3 rounded-lg px-3 py-2 ring-1 ring-inset',
                    full ? 'cursor-not-allowed opacity-60 ring-stone-200' : 'cursor-pointer',
                    !full && (role === r ? 'bg-brand-50 ring-brand-400' : 'ring-stone-200 hover:bg-stone-50'),
                  )}
                >
                  <input
                    type="radio"
                    name="role"
                    value={r}
                    checked={role === r}
                    disabled={full}
                    onChange={() => {
                      setRole(r)
                      setError(null)
                    }}
                    className="h-4 w-4 border-stone-300 text-brand-600 focus:ring-brand-500"
                  />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium text-stone-900">
                      {t(`roles.${r}`)}
                      {c && (
                        <span className="ml-1 font-normal tabular-nums text-stone-500">
                          ({c.active} / {c.limit ?? t('roleCapacity.noLimit')})
                        </span>
                      )}
                    </span>
                    {full && <span className="block text-xs text-amber-700">{t('roleCapacity.fullHint')}</span>}
                  </span>
                </label>
              )
            })}
          </div>
        </fieldset>

        {needsPosition && (
          <Field
            label={t('userForm.position')}
            hint={
              positionError ? (
                <span className="text-red-600" role="alert">
                  {errorMessage(positionError)}
                </span>
              ) : (
                t('roleChange.positionHint')
              )
            }
          >
            {(fid) => (
              <>
                <Input
                  id={fid}
                  list={`${fid}-suggestions`}
                  maxLength={POSITION_MAX_LENGTH}
                  value={position}
                  onChange={(e) => {
                    setPosition(e.target.value)
                    setError(null)
                  }}
                />
                <datalist id={`${fid}-suggestions`}>
                  {positions.data?.map((p) => <option key={p} value={p} />)}
                </datalist>
              </>
            )}
          </Field>
        )}

        <Alert tone="warning">{t('roleChange.accessReset')}</Alert>
      </form>
    </Sheet>
  )
}
