import { useTranslation } from 'react-i18next'
import { useAuth, useRefreshMeWhenStale } from '@/auth/AuthProvider'
import { RoleBadge } from '@/components/badges'
import { NavTile } from '@/components/NavTile'
import { useNavItems } from '@/layouts/nav'

export function HomePage() {
  const { t } = useTranslation()
  const { me } = useAuth()
  useRefreshMeWhenStale()
  // The top-level sections (Workstation, Settings) as large tiles; Home itself is skipped.
  const sections = useNavItems().filter((item) => !item.end)
  if (!me) return null

  return (
    <div className="space-y-6">
      <section className="rounded-2xl bg-gradient-to-br from-brand-600 to-brand-500 p-6 text-white shadow-sm">
        <p className="text-sm text-brand-100">{t('home.subtitle')}</p>
        <h1 className="mt-1 text-2xl font-semibold">
          {t('home.welcome', { name: me.user.full_name })}
        </h1>
        <div className="mt-3">
          <RoleBadge role={me.user.role} position={me.user.position} />
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        {sections.map((item) => (
          <NavTile key={item.to} item={item} size="lg" />
        ))}
      </div>
    </div>
  )
}
