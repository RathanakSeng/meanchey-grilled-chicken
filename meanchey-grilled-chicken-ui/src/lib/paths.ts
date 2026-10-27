/** App routes (frontend URLs — not API paths). Use these instead of string literals. */
export const paths = {
  home: '/',
  workstation: '/workstation',
  suppliers: '/workstation/suppliers',
  customers: '/workstation/customers',
  production: '/workstation/production',
  productionBatch: (id: string, step?: number) =>
    `/workstation/production/${id}${step ? `?step=${step}` : ''}`,
  productionPlans: '/workstation/production-plans',
  productionPlan: (batchId: string) => `/workstation/production-plans/${batchId}`,
  inventory: '/workstation/inventory',
  /** The clears list (History → Clears). */
  inventoryClears: '/workstation/inventory?tab=history&view=clears',
  inventoryClear: (id: string) => `/workstation/inventory/clears/${id}`,
  orders: '/workstation/orders',
  newOrder: '/workstation/orders/new',
  order: (id: string) => `/workstation/orders/${id}`,
  editOrder: (id: string) => `/workstation/orders/${id}/edit`,
  preparations: '/workstation/preparations',
  preparation: (id: string) => `/workstation/preparations/${id}`,
  attendance: '/attendance',
  attendanceCheck: '/attendance/check',
  myAttendance: '/attendance/me',
  attendanceEmployee: (id: string) => `/attendance/employees/${id}`,
  attendanceToday: '/attendance/today',
  attendanceRequests: '/attendance/requests',
  attendanceScheduling: '/attendance/scheduling',
  attendanceSchedulingEmployees: '/attendance/scheduling/employees',
  attendanceSchedulingEmployee: (userId: string) => `/attendance/scheduling/employees?employee=${userId}`,
  /** One workplace's scheduling. */
  attendanceSchedulingFor: (workplaceId: string) => `/attendance/scheduling/${workplaceId}`,
  settings: '/settings',
  users: '/settings/users',
  newUser: '/settings/users/new',
  user: (id: string) => `/settings/users/${id}`,
  editUser: (id: string) => `/settings/users/${id}/edit`,
  auditLogs: '/settings/audit-logs',
  userLimits: '/settings/user-limits',
  businessInfo: '/settings/business-info',
  attendanceWorkplaces: '/settings/attendance/workplaces',
  newAttendanceWorkplace: '/settings/attendance/workplaces/new',
  attendanceWorkplace: (id: string) => `/settings/attendance/workplaces/${id}`,
  profile: '/settings/profile',
} as const

/** Old top-level paths (before the Workstation/Settings sections) → their new prefix. */
export const LEGACY_PREFIXES: Record<string, string> = {
  '/users': paths.users,
  '/audit-logs': paths.auditLogs,
  '/profile': paths.profile,
}

/**
 * The route one level up: drop the last path segment.
 *   /settings/users/:id/edit → /settings/users/:id
 *   /settings/users/:id      → /settings/users
 *   /settings/users          → /settings
 *   /workstation/suppliers   → /workstation
 *   /workstation             → /
 */
export function parentPath(pathname: string): string {
  const segments = pathname.split('/').filter(Boolean)
  segments.pop()
  return `/${segments.join('/')}`
}

/** True for `prefix` itself and anything below it (not just a shared string prefix). */
export function isUnder(pathname: string, prefix: string): boolean {
  if (prefix === '/') return pathname === '/'
  return pathname === prefix || pathname.startsWith(`${prefix}/`)
}
