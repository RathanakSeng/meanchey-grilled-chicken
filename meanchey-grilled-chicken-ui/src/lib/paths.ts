/** App routes (frontend URLs — not API paths). Use these instead of string literals. */
export const paths = {
  home: '/',
  workstation: '/workstation',
  suppliers: '/workstation/suppliers',
  customers: '/workstation/customers',
  production: '/workstation/production',
  productionBatch: (id: string, step?: number) =>
    `/workstation/production/${id}${step ? `?step=${step}` : ''}`,
  settings: '/settings',
  users: '/settings/users',
  newUser: '/settings/users/new',
  user: (id: string) => `/settings/users/${id}`,
  editUser: (id: string) => `/settings/users/${id}/edit`,
  auditLogs: '/settings/audit-logs',
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
