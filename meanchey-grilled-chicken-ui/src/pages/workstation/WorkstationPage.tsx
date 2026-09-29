import { useTranslation } from 'react-i18next'
import { useRefreshMeWhenStale } from '@/auth/AuthProvider'
import { Icon } from '@/components/icons'
import { NavTile } from '@/components/NavTile'
import { Card, PageHeader } from '@/components/ui'
import { useNavChildren } from '@/layouts/nav'
import { paths } from '@/lib/paths'

/** Workstation hub: one card per Workstation child the user may open (driven by the nav tree). */
export function WorkstationPage() {
  const { t } = useTranslation()
  // Pick up newly granted / revoked permissions when the hub is opened.
  useRefreshMeWhenStale()
  const items = useNavChildren(paths.workstation)

  return (
    <>
      <PageHeader title={t('nav.workstation')} back={paths.home} />
      {items.length > 0 ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {items.map((item) => (
            <NavTile key={item.to} item={item} />
          ))}
        </div>
      ) : (
        <Card>
          <div className="flex flex-col items-center py-10 text-center">
            <span className="mb-4 inline-flex h-14 w-14 items-center justify-center rounded-full bg-brand-50 text-brand-600">
              <Icon name="lock" width={28} height={28} />
            </span>
            <h2 className="text-base font-semibold text-stone-900">
              {t('workstation.noAccessTitle')}
            </h2>
            <p className="mt-1 max-w-sm text-sm text-stone-500">{t('workstation.noAccessBody')}</p>
          </div>
        </Card>
      )}
    </>
  )
}
