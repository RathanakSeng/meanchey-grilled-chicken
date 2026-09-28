import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Icon } from '@/components/icons'
import { LanguageSwitcher } from '@/components/LanguageSwitcher'
import { ProfileMenu } from '@/components/ProfileMenu'
import { cx } from '@/components/ui'
import { parentPath } from '@/lib/paths'
import { isTelegramMiniApp, telegram } from '@/lib/telegram'
import { Brand } from './Brand'
import { useNavItems } from './nav'

/**
 * Telegram's native back button: hidden on Home, otherwise goes to the parent route
 * (/settings/users/:id → /settings/users → /settings → /). Using the route tree rather than
 * history means a deep link opened straight into the Mini App still has a sensible back target.
 */
function useTelegramBackButton() {
  const location = useLocation()
  const navigate = useNavigate()
  useEffect(() => {
    if (!isTelegramMiniApp || !telegram) return
    const back = telegram.BackButton
    const onBack = () => navigate(parentPath(location.pathname))
    if (location.pathname === '/') {
      back.hide()
    } else {
      back.show()
      back.onClick(onBack)
    }
    return () => back.offClick(onBack)
  }, [location.pathname, navigate])
}

export function MobileLayout() {
  const { t } = useTranslation()
  const items = useNavItems()
  useTelegramBackButton()

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-stone-200 bg-white/95 px-4 backdrop-blur">
        <Brand compact />
        <div className="flex items-center gap-2">
          <LanguageSwitcher />
          <ProfileMenu />
        </div>
      </header>

      <main className="flex-1 px-4 pb-24 pt-4">
        <Outlet />
      </main>

      <nav
        className="fixed inset-x-0 bottom-0 z-30 border-t border-stone-200 bg-white"
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
      >
        <ul className="flex">
          {items.map((item) => (
            <li key={item.to} className="flex-1">
              <NavLink
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cx(
                    'flex flex-col items-center gap-0.5 px-1 py-2 text-[11px] font-medium',
                    isActive ? 'text-brand-600' : 'text-stone-500',
                  )
                }
              >
                <Icon name={item.icon} width={22} height={22} />
                <span className="max-w-full truncate">{t(item.labelKey)}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  )
}
