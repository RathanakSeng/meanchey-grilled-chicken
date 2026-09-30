import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Alert, Badge, Button, Card, Input, PageHeader, Spinner, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useFormatDate } from '@/lib/format'
import { paths } from '@/lib/paths'
import { ROLE_LIMIT_MAX, type RoleLimit } from '@/lib/types'
import { ROLE_CAPACITY_KEY, ROLE_LIMITS_KEY } from '@/lib/useRoleCapacity'

function LimitRow({ limit }: { limit: RoleLimit }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const formatDate = useFormatDate()
  const canBeUnlimited = limit.role !== 'general_manager'
  const [unlimited, setUnlimited] = useState(limit.max_active === null)
  const [value, setValue] = useState(limit.max_active === null ? '' : String(limit.max_active))
  const [saved, setSaved] = useState(false)

  // Server values after a save or refetch.
  useEffect(() => {
    setUnlimited(limit.max_active === null)
    setValue(limit.max_active === null ? '' : String(limit.max_active))
  }, [limit.max_active])

  const number = /^\d+$/.test(value.trim()) ? Number(value) : Number.NaN
  const valid = unlimited || (number >= 1 && number <= ROLE_LIMIT_MAX)
  const next = unlimited ? null : number
  const dirty = next !== limit.max_active

  const save = useMutation({
    mutationFn: async () =>
      (await api.put<RoleLimit[]>(`/settings/role-limits/${limit.role}`, { max_active: next })).data,
    onSuccess: (rows) => {
      queryClient.setQueryData(ROLE_LIMITS_KEY, rows)
      void queryClient.invalidateQueries({ queryKey: ROLE_CAPACITY_KEY })
      setSaved(true)
    },
  })

  const plural = t(`userLimits.plural.${limit.role}`)
  return (
    <li className="py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-base font-semibold text-stone-900">{t(`roles.${limit.role}`)}</span>
        <span className="text-sm tabular-nums text-stone-600">
          {t('userLimits.activeOf', {
            active: limit.active,
            limit: limit.max_active ?? t('userLimits.unlimited'),
          })}
        </span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <div className="w-28 shrink-0">
          <Input
            type="text"
            inputMode="numeric"
            aria-label={t('userLimits.maxActive', { role: t(`roles.${limit.role}`) })}
            className={cx('h-11 tabular-nums', !valid && 'ring-red-400')}
            value={unlimited ? '' : value}
            placeholder={unlimited ? '∞' : ''}
            disabled={unlimited}
            onChange={(e) => {
              setValue(e.target.value)
              setSaved(false)
            }}
          />
        </div>
        {canBeUnlimited && (
          <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-stone-700">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-stone-300 accent-brand-600"
              checked={unlimited}
              onChange={(e) => {
                setUnlimited(e.target.checked)
                if (!e.target.checked && !value) setValue(String(limit.active || 1))
                setSaved(false)
              }}
            />
            {t('userLimits.unlimited')}
          </label>
        )}
        <Button
          variant="secondary"
          disabled={!valid || !dirty}
          loading={save.isPending}
          onClick={() => save.mutate()}
        >
          {t('common.save')}
        </Button>
        {saved && !dirty && <Badge tone="green">{t('common.saved')}</Badge>}
      </div>
      {!valid && (
        <p className="mt-1 text-xs text-red-600">
          {t(canBeUnlimited ? 'userLimits.range' : 'userLimits.rangeGm', { max: ROLE_LIMIT_MAX })}
        </p>
      )}
      {limit.over_limit && limit.max_active !== null && (
        <Alert tone="warning" className="mt-3">
          {t('userLimits.overLimit', { active: limit.active, limit: limit.max_active, roles: plural })}
        </Alert>
      )}
      {save.isError && (
        <Alert tone="error" className="mt-3">
          {errorMessage(save.error)}
        </Alert>
      )}
      {limit.updated_at && limit.updated_by && (
        <p className="mt-2 text-xs text-stone-500">
          {t('userLimits.lastChanged', {
            name: limit.updated_by.is_system ? t('audit.system') : limit.updated_by.full_name,
            time: formatDate(limit.updated_at),
          })}
        </p>
      )}
    </li>
  )
}

/**
 * Settings → User limits (superadmin only): how many active general managers, supervisors and
 * staff there may be. Lowering a limit below the active count keeps everyone; the role is full
 * until some leave it.
 */
export function UserLimitsPage() {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const query = useQuery({
    queryKey: ROLE_LIMITS_KEY,
    queryFn: async () => (await api.get<RoleLimit[]>('/settings/role-limits')).data,
  })

  return (
    <>
      <PageHeader title={t('userLimits.title')} subtitle={t('userLimits.subtitle')} back={paths.settings} />
      {query.isPending && (
        <div className="flex justify-center py-10 text-brand-600">
          <Spinner />
        </div>
      )}
      {query.isError && <Alert tone="error">{errorMessage(query.error)}</Alert>}
      {query.data && (
        <Card className="max-w-2xl">
          <ul className="divide-y divide-stone-100">
            {query.data.map((limit) => (
              <LimitRow key={limit.role} limit={limit} />
            ))}
          </ul>
          <p className="mt-4 text-xs text-stone-500">{t('userLimits.note')}</p>
        </Card>
      )}
    </>
  )
}
