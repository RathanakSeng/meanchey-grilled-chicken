import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter, Navigate, useLocation } from 'react-router-dom'
import { PublicOnly, RequireAccess, RequireAuth } from '@/auth/guards'
import { Spinner } from '@/components/ui'
import { AppShell } from '@/layouts/AppShell'
import { LEGACY_PREFIXES, paths } from '@/lib/paths'
import { AUDIT_ROLES, ROLE_LIMIT_ROLES } from '@/lib/roles'
import { ChangePasswordPage } from '@/pages/ChangePasswordPage'
import { HomePage } from '@/pages/HomePage'
import { LoginPage } from '@/pages/LoginPage'
import { CUSTOMERS, SUPPLIERS } from '@/pages/workstation/partners/config'
import { PartnerListPage } from '@/pages/workstation/partners/PartnerListPage'
import { WorkstationPage } from '@/pages/workstation/WorkstationPage'
import { AuditLogPage } from '@/pages/settings/AuditLogPage'
import { ProfilePage } from '@/pages/settings/ProfilePage'
import { SettingsPage } from '@/pages/settings/SettingsPage'
import { UserLimitsPage } from '@/pages/settings/UserLimitsPage'
import { UserDetailPage } from '@/pages/settings/users/UserDetailPage'
import { UserFormPage } from '@/pages/settings/users/UserFormPage'
import { UsersListPage } from '@/pages/settings/users/UsersListPage'
import { NotFoundPage } from '@/pages/StatusPages'

/**
 * Old URL (before the Workstation/Settings sections) → new URL, keeping the rest of the path, the query string
 * and the hash: /users/abc/edit?x=1 → /settings/users/abc/edit?x=1.
 */
function LegacyRedirect({ from }: { from: string }) {
  const { pathname, search, hash } = useLocation()
  const rest = pathname.slice(from.length)
  return <Navigate to={`${LEGACY_PREFIXES[from]}${rest}${search}${hash}`} replace />
}

// Production is the largest feature and only some users have it: its pages are a separate chunk,
// loaded on first visit (after the access check, so users without access never download it).
const ProductionListPage = lazy(() =>
  import('@/pages/workstation/production/ProductionListPage').then((m) => ({
    default: m.ProductionListPage,
  })),
)
const ProductionBatchPage = lazy(() =>
  import('@/pages/workstation/production/ProductionBatchPage').then((m) => ({
    default: m.ProductionBatchPage,
  })),
)

// Packaging plans: another lazy chunk, only for plan holders.
const PlanListPage = lazy(() =>
  import('@/pages/workstation/production-plans/PlanListPage').then((m) => ({ default: m.PlanListPage })),
)
const PlanPage = lazy(() =>
  import('@/pages/workstation/production-plans/PlanPage').then((m) => ({ default: m.PlanPage })),
)

function PageLoading({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="flex justify-center py-16 text-brand-600">
          <Spinner />
        </div>
      }
    >
      {children}
    </Suspense>
  )
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
            path: paths.workstation,
            children: [
              { index: true, element: <WorkstationPage /> },
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
              {
                path: 'production',
                children: [
                  {
                    index: true,
                    element: (
                      <RequireAccess permission="production.view">
                        <PageLoading>
                          <ProductionListPage />
                        </PageLoading>
                      </RequireAccess>
                    ),
                  },
                  {
                    path: ':batchId',
                    element: (
                      <RequireAccess permission="production.view">
                        <PageLoading>
                          <ProductionBatchPage />
                        </PageLoading>
                      </RequireAccess>
                    ),
                  },
                ],
              },
              {
                path: 'production-plans',
                element: <RequireAccess permission="production_plan.view" />,
                children: [
                  {
                    index: true,
                    element: (
                      <PageLoading>
                        <PlanListPage />
                      </PageLoading>
                    ),
                  },
                  {
                    path: ':batchId',
                    element: (
                      <PageLoading>
                        <PlanPage />
                      </PageLoading>
                    ),
                  },
                ],
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
              {
                path: 'user-limits',
                element: (
                  <RequireAccess roles={ROLE_LIMIT_ROLES}>
                    <UserLimitsPage />
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
