import type { ReactNode } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { FullScreenSpinner } from '@/components/ui'
import { ForbiddenPage, OfflinePage } from '@/pages/StatusPages'
import { TelegramErrorPage } from '@/pages/StatusPages'
import { useAuth } from './AuthProvider'
import { useCanAccess, type AccessRule } from './usePermission'

const CHANGE_PASSWORD_PATH = '/change-password'

/** Requires a signed-in user; sends users with a pending password change to that page. */
export function RequireAuth() {
  const { status, me, telegramError, refreshMe } = useAuth()
  const location = useLocation()

  if (status === 'booting') return <FullScreenSpinner />
  if (status === 'offline') return <OfflinePage onRetry={() => void refreshMe()} />
  if (status === 'anonymous') {
    if (telegramError) return <TelegramErrorPage code={telegramError} />
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }
  const onChangePassword = location.pathname === CHANGE_PASSWORD_PATH
  if (me?.user.must_change_password && !onChangePassword) {
    return <Navigate to={CHANGE_PASSWORD_PATH} replace />
  }
  if (!me?.user.must_change_password && onChangePassword) return <Navigate to="/" replace />
  return <Outlet />
}

/** Only for signed-out users (the login page). */
export function PublicOnly() {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'booting') return <FullScreenSpinner />
  if (status === 'authenticated') {
    const from = (location.state as { from?: string } | null)?.from
    return <Navigate to={from && from !== '/login' ? from : '/'} replace />
  }
  return <Outlet />
}

/** Route guard by permission and/or role. Renders children, or the nested route. */
export function RequireAccess({ children, ...rule }: AccessRule & { children?: ReactNode }) {
  const canAccess = useCanAccess()
  if (!canAccess(rule)) return <ForbiddenPage />
  return <>{children ?? <Outlet />}</>
}
