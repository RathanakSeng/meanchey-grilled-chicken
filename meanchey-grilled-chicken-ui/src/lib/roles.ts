import type { Role } from './types'

/**
 * Role checks that involve the superadmin, in one place. The API already shows the superadmin as
 * "System" to everyone else, and its role label is "System" too (roles.superadmin).
 */

export function isSuperadmin(role: Role | null | undefined): boolean {
  return role === 'superadmin'
}

/** The superadmin's login name (its password-equals-username check). */
export const SUPERADMIN_LOGIN = 'superadmin'

/** Who may set the role limits (Settings → User limits). */
export const ROLE_LIMIT_ROLES: Role[] = ['superadmin']

/** Employees whose attendance is recorded (check in / check out from the Mini App). */
export const TRACKED_ROLES: Role[] = ['staff', 'supervisor']

/** Settings → Workplaces: any workplace permission (schedules are in Scheduling). */
export const WORKPLACE_ACCESS = [
  { permission: 'attendance.workplace_view' },
  { permission: 'attendance.workplace_update' },
  { permission: 'attendance.workplace_manage' },
]

/** Attendance → Requests: tracked employees (their own) and reviewers (attendance.requests_review). */
export const REQUESTS_ACCESS = [{ roles: TRACKED_ROLES }, { permission: 'attendance.requests_review' }]

/** Scheduling (calendar, holidays, weekdays, shifts): view with attendance.view, edit with
 *  attendance.scheduling. */
export const SCHEDULING_ACCESS = [{ permission: 'attendance.view' }, { permission: 'attendance.scheduling' }]
