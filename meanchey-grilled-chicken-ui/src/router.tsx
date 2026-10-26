import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter, Navigate, useLocation } from 'react-router-dom'
import { PublicOnly, RequireAccess, RequireAuth } from '@/auth/guards'
import { Spinner } from '@/components/ui'
import { AppShell } from '@/layouts/AppShell'
import { LEGACY_PREFIXES, paths } from '@/lib/paths'
import {
  REQUESTS_ACCESS,
  ROLE_LIMIT_ROLES,
  SCHEDULING_ACCESS,
  TRACKED_ROLES,
  WORKPLACE_ACCESS,
} from '@/lib/roles'
import { AttendancePage } from '@/pages/attendance/AttendancePage'
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

// Inventory: a lazy chunk for holders of inventory.view.
const InventoryPage = lazy(() =>
  import('@/pages/workstation/inventory/InventoryPage').then((m) => ({ default: m.InventoryPage })),
)
// Preparations: a lazy chunk for holders of preparation.view.
const PreparationListPage = lazy(() =>
  import('@/pages/workstation/preparations/PreparationListPage').then((m) => ({
    default: m.PreparationListPage,
  })),
)
const PreparationPage = lazy(() =>
  import('@/pages/workstation/preparations/PreparationPage').then((m) => ({ default: m.PreparationPage })),
)
// Orders: a lazy chunk for holders of orders.view.
const OrderListPage = lazy(() =>
  import('@/pages/workstation/orders/OrderListPage').then((m) => ({ default: m.OrderListPage })),
)
const OrderPage = lazy(() => import('@/pages/workstation/orders/OrderPage').then((m) => ({ default: m.OrderPage })))
const OrderFormPage = lazy(() =>
  import('@/pages/workstation/orders/OrderFormPage').then((m) => ({ default: m.OrderFormPage })),
)
// Business info: a small lazy chunk for the superadmin (and GMs given it).
const BusinessInfoPage = lazy(() =>
  import('@/pages/settings/BusinessInfoPage').then((m) => ({ default: m.BusinessInfoPage })),
)
// Packaging plans: another lazy chunk, only for plan holders.
const PlanListPage = lazy(() =>
  import('@/pages/workstation/production-plans/PlanListPage').then((m) => ({ default: m.PlanListPage })),
)
const PlanPage = lazy(() =>
  import('@/pages/workstation/production-plans/PlanPage').then((m) => ({ default: m.PlanPage })),
)

// Attendance: the check screen, Today and the settings pages carry Leaflet / the day view, so
// they are lazy chunks; the hub, My day and the Home card are small and in the main bundle.
const CheckPage = lazy(() => import('@/pages/attendance/CheckPage').then((m) => ({ default: m.CheckPage })))
const MyAttendancePage = lazy(() =>
  import('@/pages/attendance/MyAttendancePage').then((m) => ({ default: m.MyAttendancePage })),
)
const EmployeeAttendancePage = lazy(() =>
  import('@/pages/attendance/MyAttendancePage').then((m) => ({ default: m.EmployeeAttendancePage })),
)
const RequestsPage = lazy(() =>
  import('@/pages/attendance/requests/RequestsPage').then((m) => ({ default: m.RequestsPage })),
)
const TodayPage = lazy(() => import('@/pages/attendance/TodayPage').then((m) => ({ default: m.TodayPage })))
const SchedulingListPage = lazy(() =>
  import('@/pages/attendance/scheduling/SchedulingListPage').then((m) => ({ default: m.SchedulingListPage })),
)
const EmployeeSchedulesPage = lazy(() =>
  import('@/pages/attendance/scheduling/EmployeeSchedulesPage').then((m) => ({ default: m.EmployeeSchedulesPage })),
)
const SchedulingPage = lazy(() =>
  import('@/pages/attendance/scheduling/SchedulingPage').then((m) => ({ default: m.SchedulingPage })),
)
const WorkplacesPage = lazy(() =>
  import('@/pages/settings/workplaces/WorkplacesPage').then((m) => ({ default: m.WorkplacesPage })),
)
const WorkplacePage = lazy(() =>
  import('@/pages/settings/workplaces/WorkplacePage').then((m) => ({ default: m.WorkplacePage })),
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
                path: 'inventory',
                element: (
                  <RequireAccess permission="inventory.view">
                    <PageLoading>
                      <InventoryPage />
                    </PageLoading>
                  </RequireAccess>
                ),
              },
              {
                path: 'orders',
                element: <RequireAccess permission="orders.view" />,
                children: [
                  {
                    index: true,
                    element: (
                      <PageLoading>
                        <OrderListPage />
                      </PageLoading>
                    ),
                  },
                  {
                    path: 'new',
                    element: (
                      <RequireAccess permission="orders.create">
                        <PageLoading>
                          <OrderFormPage key="new" mode="create" />
                        </PageLoading>
                      </RequireAccess>
                    ),
                  },
                  {
                    path: ':orderId',
                    element: (
                      <PageLoading>
                        <OrderPage />
                      </PageLoading>
                    ),
                  },
                  {
                    path: ':orderId/edit',
                    element: (
                      <RequireAccess permission="orders.update">
                        <PageLoading>
                          <OrderFormPage key="edit" mode="edit" />
                        </PageLoading>
                      </RequireAccess>
                    ),
                  },
                ],
              },
              {
                path: 'preparations',
                element: <RequireAccess permission="preparation.view" />,
                children: [
                  {
                    index: true,
                    element: (
                      <PageLoading>
                        <PreparationListPage />
                      </PageLoading>
                    ),
                  },
                  {
                    path: ':preparationId',
                    element: (
                      <PageLoading>
                        <PreparationPage />
                      </PageLoading>
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
            path: paths.attendance,
            element: <RequireAccess anyOf={[{ roles: TRACKED_ROLES }, ...SCHEDULING_ACCESS, ...REQUESTS_ACCESS]} />,
            children: [
              { index: true, element: <AttendancePage /> },
              {
                path: 'check',
                element: (
                  <RequireAccess roles={TRACKED_ROLES}>
                    <PageLoading>
                      <CheckPage />
                    </PageLoading>
                  </RequireAccess>
                ),
              },
              {
                path: 'me',
                element: (
                  <RequireAccess roles={TRACKED_ROLES}>
                    <PageLoading>
                      <MyAttendancePage />
                    </PageLoading>
                  </RequireAccess>
                ),
              },
              {
                path: 'today',
                element: (
                  <RequireAccess permission="attendance.view">
                    <PageLoading>
                      <TodayPage />
                    </PageLoading>
                  </RequireAccess>
                ),
              },
              {
                path: 'requests',
                element: (
                  <RequireAccess anyOf={REQUESTS_ACCESS}>
                    <PageLoading>
                      <RequestsPage />
                    </PageLoading>
                  </RequireAccess>
                ),
              },
              {
                path: 'scheduling',
                element: (
                  <RequireAccess anyOf={SCHEDULING_ACCESS}>
                    <PageLoading>
                      <SchedulingListPage />
                    </PageLoading>
                  </RequireAccess>
                ),
              },
              {
                path: 'scheduling/employees',
                element: (
                  <RequireAccess permission="attendance.scheduling">
                    <PageLoading>
                      <EmployeeSchedulesPage />
                    </PageLoading>
                  </RequireAccess>
                ),
              },
              {
                path: 'scheduling/:workplaceId',
                element: (
                  <RequireAccess anyOf={SCHEDULING_ACCESS}>
                    <PageLoading>
                      <SchedulingPage />
                    </PageLoading>
                  </RequireAccess>
                ),
              },
              {
                path: 'employees/:id',
                element: (
                  <RequireAccess permission="attendance.view">
                    <PageLoading>
                      <EmployeeAttendancePage />
                    </PageLoading>
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
                  <RequireAccess permission="audit.view">
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
              {
                path: 'business-info',
                element: (
                  <RequireAccess permission="settings.business_info">
                    <PageLoading>
                      <BusinessInfoPage />
                    </PageLoading>
                  </RequireAccess>
                ),
              },
              {
                path: 'attendance/workplaces',
                element: <RequireAccess anyOf={WORKPLACE_ACCESS} />,
                children: [
                  {
                    index: true,
                    element: (
                      <PageLoading>
                        <WorkplacesPage />
                      </PageLoading>
                    ),
                  },
                  {
                    path: 'new',
                    element: (
                      <RequireAccess permission="attendance.workplace_manage">
                        <PageLoading>
                          <WorkplacePage />
                        </PageLoading>
                      </RequireAccess>
                    ),
                  },
                  {
                    path: ':id',
                    element: (
                      <PageLoading>
                        <WorkplacePage />
                      </PageLoading>
                    ),
                  },
                ],
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
