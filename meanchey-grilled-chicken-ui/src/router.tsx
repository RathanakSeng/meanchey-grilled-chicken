import { createBrowserRouter, Navigate, useLocation } from 'react-router-dom'
import { PublicOnly, RequireAccess, RequireAuth } from '@/auth/guards'
import { AppShell } from '@/layouts/AppShell'
import { LEGACY_PREFIXES, paths } from '@/lib/paths'
import { AUDIT_ROLES } from '@/lib/roles'
import { ChangePasswordPage } from '@/pages/ChangePasswordPage'
import { HomePage } from '@/pages/HomePage'
import { LoginPage } from '@/pages/LoginPage'
import { CUSTOMERS, SUPPLIERS } from '@/pages/production/partners/config'
import { PartnerListPage } from '@/pages/production/partners/PartnerListPage'
import { ProductionPage } from '@/pages/production/ProductionPage'
import { AuditLogPage } from '@/pages/settings/AuditLogPage'
import { ProfilePage } from '@/pages/settings/ProfilePage'
import { SettingsPage } from '@/pages/settings/SettingsPage'
import { UserDetailPage } from '@/pages/settings/users/UserDetailPage'
import { UserFormPage } from '@/pages/settings/users/UserFormPage'
import { UsersListPage } from '@/pages/settings/users/UsersListPage'
import { NotFoundPage } from '@/pages/StatusPages'

/**
 * Old URL (before Production/Settings) → new URL, keeping the rest of the path, the query string
 * and the hash: /users/abc/edit?x=1 → /settings/users/abc/edit?x=1.
 */
function LegacyRedirect({ from }: { from: string }) {
  const { pathname, search, hash } = useLocation()
  const rest = pathname.slice(from.length)
  return <Navigate to={`${LEGACY_PREFIXES[from]}${rest}${search}${hash}`} replace />
}

const legacyRoutes = Object.keys(LEGACY_PREFIXES).flatMap((from) => [
  { path: from, element: <LegacyRedirect from={from} /> },
  { path: `${from}/*`, element: <LegacyRedirect from={from} /> },
])

// Route guards are UX only; every API endpoint enforces the same rules.
export const router = createBrowserRouter([
  {
    element: <PublicOnly />,
    children: [{ path: '/login', element: <LoginPage /> }],
  },
  {
    element: <RequireAuth />,
    children: [
      { path: '/change-password', element: <ChangePasswordPage /> },
      {
        element: <AppShell />,
        children: [
          { index: true, element: <HomePage /> },
          {
            path: paths.production,
            children: [
              { index: true, element: <ProductionPage /> },
              {
                path: 'suppliers',
                element: (
                  <RequireAccess permission="suppliers.view">
                    <PartnerListPage key="suppliers" config={SUPPLIERS} />
                  </RequireAccess>
                ),
              },
              {
                path: 'customers',
                element: (
                  <RequireAccess permission="customers.view">
                    <PartnerListPage key="customers" config={CUSTOMERS} />
                  </RequireAccess>
                ),
              },
            ],
          },
          {
            path: paths.settings,
            children: [
              { index: true, element: <SettingsPage /> },
              {
                path: 'users',
                element: <RequireAccess permission="users.view" />,
                children: [
                  { index: true, element: <UsersListPage /> },
                  {
                    path: 'new',
                    element: (
                      <RequireAccess permission="users.create">
                        <UserFormPage mode="create" />
                      </RequireAccess>
                    ),
                  },
                  { path: ':id', element: <UserDetailPage /> },
                  {
                    path: ':id/edit',
                    element: (
                      <RequireAccess permission="users.update">
                        <UserFormPage mode="edit" />
                      </RequireAccess>
                    ),
                  },
                ],
              },
              {
                path: 'audit-logs',
                element: (
                  <RequireAccess roles={AUDIT_ROLES}>
                    <AuditLogPage />
                  </RequireAccess>
                ),
              },
              { path: 'profile', element: <ProfilePage /> },
            ],
          },
          ...legacyRoutes,
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
])
