import { useTranslation } from 'react-i18next'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { Icon } from '@/components/icons'
import { LanguageSwitcher } from '@/components/LanguageSwitcher'
import { NotificationBell } from '@/components/NotificationBell'
import { ProfileMenu } from '@/components/ProfileMenu'
import { cx } from '@/components/ui'
import { isUnder } from '@/lib/paths'
import { Brand } from './Brand'
import { NavBadge } from '@/components/NavBadge'
import { useNavItems } from './nav'

export function DesktopLayout() {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const items = useNavItems()

  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 flex h-screen w-64 shrink-0 flex-col border-r border-stone-200 bg-white">
        <div className="px-5 py-5">
          <Brand />
        </div>
        <nav className="flex-1 space-y-1 overflow-y-auto px-3 pb-4">
          {items.map((item) => {
            const inSection = item.end ? pathname === item.to : isUnder(pathname, item.to)
            const onSectionPage = pathname === item.to
            const children = item.children ?? []
            return (
              <div key={item.to}>
                <Link
                  to={item.to}
                  aria-current={onSectionPage ? 'page' : undefined}
                  className={cx(
                    'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition',
                    // The section itself is highlighted; when a child page is open the parent
                    // keeps the brand color but only the child gets the filled background.
                    onSectionPage
                      ? 'bg-brand-50 text-brand-700'
                      : inSection
                        ? 'text-brand-700 hover:bg-stone-50'
                        : 'text-stone-600 hover:bg-stone-50 hover:text-stone-900',
                  )}
                >
                  <Icon name={item.icon} />
                  {t(item.labelKey)}
                </Link>
                {inSection && children.length > 0 && (
                  <ul className="mb-1 ml-5 mt-1 space-y-0.5 border-l border-stone-200 pl-3">
                    {children.map((child) => (
                      <li key={child.to}>
                        <NavLink
                          to={child.to}
                          className={({ isActive }) =>
                            cx(
                              'flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-sm transition',
                              isActive
                                ? 'bg-brand-50 font-medium text-brand-700'
                                : 'text-stone-600 hover:bg-stone-50 hover:text-stone-900',
                            )
                          }
                        >
                          <Icon name={child.icon} width={16} height={16} />
                          {t(child.labelKey)}
                          <NavBadge item={child} />
                        </NavLink>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )
          })}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-end gap-4 border-b border-stone-200 bg-white/90 px-6 backdrop-blur">
          <LanguageSwitcher />
          <NotificationBell />
          <ProfileMenu />
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
