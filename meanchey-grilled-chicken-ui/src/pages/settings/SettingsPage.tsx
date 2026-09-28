import { useTranslation } from 'react-i18next'
import { useRefreshMeWhenStale } from '@/auth/AuthProvider'
import { NavTile } from '@/components/NavTile'
import { PageHeader } from '@/components/ui'
import { useNavChildren } from '@/layouts/nav'
import { paths } from '@/lib/paths'

/** Settings hub: one card per Settings child the user may open (driven by the nav tree). */
export function SettingsPage() {
  const { t } = useTranslation()
  // Pick up permission changes (e.g. a revoked users.view) when the hub is opened.
  useRefreshMeWhenStale()
  const items = useNavChildren(paths.settings)

  return (
    <>
      <PageHeader title={t('nav.settings')} back={paths.home} />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => (
          <NavTile key={item.to} item={item} />
        ))}
      </div>
    </>
  )
}
