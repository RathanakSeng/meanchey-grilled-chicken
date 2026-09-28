import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ME_QUERY_KEY, useAuth } from '@/auth/AuthProvider'
import { SegmentedControl } from '@/components/SegmentedControl'
import { Alert, Badge, Card, EmptyState, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useLocalized } from '@/lib/format'
import type { Feature, FeatureLevel, UserFeatures } from '@/lib/types'

export function userFeaturesKey(userId: string) {
  return ['user-features', userId] as const
}

/**
 * Feature access levels (Off / View only / Full access) for one user, grouped by menu.
 * The data comes from the parent (`UserDetailPage`), which also decides whether to show the tab.
 */
export function UserAccessTab({ userId, data }: { userId: string; data: UserFeatures }) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const errorMessage = useErrorMessage()
  const queryClient = useQueryClient()
  const { me } = useAuth()
  const key = userFeaturesKey(userId)

  const setLevel = useMutation({
    mutationFn: async ({ feature, level }: { feature: Feature; level: FeatureLevel }) =>
      (await api.put<Feature>(`/users/${userId}/features/${feature.code}`, { level })).data,
    // Optimistic: show the new level at once; on error the cached data is put back.
    onMutate: async ({ feature, level }) => {
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData<UserFeatures>(key)
      queryClient.setQueryData<UserFeatures>(key, (old) =>
        old && {
          ...old,
          menus: old.menus.map((m) => ({
            ...m,
            features: m.features.map((f) =>
              f.code === feature.code ? { ...f, current_level: level } : f,
            ),
          })),
        },
      )
      return { previous }
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(key, context.previous)
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: key })
      if (me?.user.id === userId) void queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY })
    },
  })

  if (data.menus.length === 0) {
    return (
      <Card>
        <EmptyState>{t('access.empty')}</EmptyState>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl bg-stone-100/70 px-4 py-3 text-sm text-stone-600">
        <p className="font-medium text-stone-800">{t('access.legendTitle')}</p>
        <p>{t('access.legendView')}</p>
        <p>{t('access.legendFull')}</p>
      </div>

      {setLevel.isError && <Alert tone="error">{errorMessage(setLevel.error)}</Alert>}

      {data.menus.map((menu) => (
        <Card key={menu.menu} title={t(`access.menus.${menu.menu}`)}>
          <ul className="-my-3 divide-y divide-stone-100">
            {menu.features.map((f) => {
              const busy = setLevel.isPending && setLevel.variables?.feature.code === f.code
              return (
                <li
                  key={f.code}
                  className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-2 font-medium text-stone-900">
                      {localized(f)}
                      {f.current_level === 'custom' && <Badge>{t('access.levels.custom')}</Badge>}
                      {busy && <Spinner className="h-4 w-4 text-brand-600" />}
                    </p>
                    <p className="text-sm text-stone-500">{localized(f, 'description')}</p>
                  </div>
                  <SegmentedControl<FeatureLevel>
                    label={localized(f)}
                    segments={f.levels.map((level) => ({
                      value: level,
                      label: t(`access.levels.${level}`),
                    }))}
                    value={f.current_level}
                    // From Off, View only is the suggested next step (still needs a click).
                    suggested={f.current_level === 'off' ? 'view' : undefined}
                    suggestedLabel={t('access.suggested')}
                    disabled={!f.can_edit || setLevel.isPending}
                    onChange={(level) => {
                      setLevel.reset()
                      setLevel.mutate({ feature: f, level })
                    }}
                  />
                </li>
              )
            })}
          </ul>
        </Card>
      ))}
    </div>
  )
}
