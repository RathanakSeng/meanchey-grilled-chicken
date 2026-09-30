import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import type { NavItem } from '@/layouts/nav'
import { NavBadge } from './NavBadge'
import { cx } from './ui'
import { Icon } from './icons'

/** A card linking to a nav item: icon, title, one-line description. */
export function NavTile({ item, size = 'md' }: { item: NavItem; size?: 'md' | 'lg' }) {
  const { t } = useTranslation()
  const large = size === 'lg'
  return (
    <Link
      to={item.to}
      className={cx(
        'group flex items-center gap-4 rounded-2xl bg-white shadow-sm ring-1 ring-stone-200 transition',
        'hover:ring-brand-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500',
        large ? 'p-5 sm:p-6' : 'p-4',
      )}
    >
      <span
        className={cx(
          'inline-flex shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600',
          large ? 'h-14 w-14' : 'h-11 w-11',
        )}
      >
        <Icon name={item.icon} width={large ? 28 : 22} height={large ? 28 : 22} />
      </span>
      <span className="min-w-0 flex-1">
        <span
          className={cx('flex items-center gap-2 font-semibold text-stone-900', large ? 'text-lg' : 'text-base')}
        >
          {t(item.labelKey)}
          <NavBadge item={item} />
        </span>
        {item.descriptionKey && (
          <span className="mt-0.5 block text-sm text-stone-500">{t(item.descriptionKey)}</span>
        )}
      </span>
      <Icon
        name="chevronRight"
        className="shrink-0 text-stone-400 transition group-hover:translate-x-0.5 group-hover:text-brand-600"
      />
    </Link>
  )
}
