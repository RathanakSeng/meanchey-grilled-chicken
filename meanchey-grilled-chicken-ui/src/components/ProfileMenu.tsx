import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '@/auth/AuthProvider'
import { initials } from '@/lib/format'
import { paths } from '@/lib/paths'
import { Icon } from './icons'

export function Avatar({ name, className }: { name: string; className?: string }) {
  return (
    <span
      className={
        'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-100 text-sm font-semibold text-brand-700 ' +
        (className ?? '')
      }
    >
      {initials(name)}
    </span>
  )
}

export function ProfileMenu() {
  const { me, logout } = useAuth()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  if (!me) return null
  const { user } = me

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-full p-0.5 hover:ring-2 hover:ring-brand-200"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <Avatar name={user.full_name} />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-40 mt-2 w-60 overflow-hidden rounded-xl bg-white shadow-lg ring-1 ring-stone-200"
        >
          <div className="border-b border-stone-100 px-4 py-3">
            <p className="truncate text-sm font-semibold text-stone-900">{user.full_name}</p>
            <p className="truncate text-xs text-stone-500">
              {t(`roles.${user.role}`)}
              {user.telegram_username && ` · @${user.telegram_username}`}
            </p>
          </div>
          <Link
            to={paths.profile}
            role="menuitem"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 px-4 py-2.5 text-sm text-stone-700 hover:bg-stone-50"
          >
            <Icon name="user" width={16} height={16} />
            {t('nav.profile')}
          </Link>
          <button
            type="button"
            role="menuitem"
            onClick={async () => {
              setOpen(false)
              await logout()
              navigate('/login', { replace: true })
            }}
            className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-red-600 hover:bg-red-50"
          >
            <Icon name="logout" width={16} height={16} />
            {t('nav.logout')}
          </button>
        </div>
      )}
    </div>
  )
}
