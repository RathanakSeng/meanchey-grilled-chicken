import { useCanAccess, type AccessRule } from '@/auth/usePermission'
import type { IconName } from '@/components/icons'
import { paths } from '@/lib/paths'
import {
  REQUESTS_ACCESS,
  ROLE_LIMIT_ROLES,
  SCHEDULING_ACCESS,
  TRACKED_ROLES,
  WORKPLACE_ACCESS,
} from '@/lib/roles'

export type NavBadgeKind = 'pendingPlans' | 'pendingRequests'

export interface NavItem extends AccessRule {
  to: string
  labelKey: string
  /** One-line description, shown on the Home tiles and the Settings hub cards. */
  descriptionKey?: string
  icon: IconName
  /** Match only the exact path when highlighting (used for Home). */
  end?: boolean
  /**
   * Keep the section visible even when none of its children are visible, so its hub page can
   * explain that nothing is available yet (Workstation for staff without partner permissions).
   */
  keepWhenEmpty?: boolean
  /** A count shown next to the item (sidebar, hub card), e.g. plans waiting to be set. */
  badge?: NavBadgeKind
  children?: NavItem[]
}

/**
 * The app menu, as a tree. Items render only when the user passes their `permission` / `roles`
 * rule; a parent with children is shown only if at least one child is visible.
 *
 * New feature? Add a child under Workstation or Settings (or a new top-level item) with the
 * permission that guards its route. Home, the sidebar, the bottom nav and the Settings hub all
 * read from this tree.
 */
export const NAV_ITEMS: NavItem[] = [
  { to: paths.home, labelKey: 'nav.home', icon: 'home', end: true },
  {
    to: paths.workstation,
    labelKey: 'nav.workstation',
    descriptionKey: 'home.workstationDescription',
    icon: 'flame',
    keepWhenEmpty: true,
    children: [
      {
        to: paths.suppliers,
        labelKey: 'nav.suppliers',
        descriptionKey: 'suppliers.description',
        icon: 'truck',
        permission: 'suppliers.view',
      },
      {
        to: paths.customers,
        labelKey: 'nav.customers',
        descriptionKey: 'customers.description',
        icon: 'store',
        permission: 'customers.view',
      },
      {
        to: paths.preparations,
        labelKey: 'nav.preparations',
        descriptionKey: 'preparations.description',
        icon: 'beaker',
        permission: 'preparation.view',
      },
      {
        to: paths.production,
        labelKey: 'nav.production',
        descriptionKey: 'production.description',
        icon: 'chicken',
        permission: 'production.view',
      },
      {
        to: paths.productionPlans,
        labelKey: 'nav.productionPlans',
        descriptionKey: 'plans.description',
        icon: 'clipboard',
        permission: 'production_plan.view',
        badge: 'pendingPlans',
      },
      {
        to: paths.inventory,
        labelKey: 'nav.inventory',
        descriptionKey: 'inventory.description',
        icon: 'boxes',
        permission: 'inventory.view',
      },
      {
        to: paths.orders,
        labelKey: 'nav.orders',
        descriptionKey: 'orders.description',
        icon: 'receipt',
        permission: 'orders.view',
      },
    ],
  },
  {
    // Tracked employees (their own day), holders of attendance.view (everyone's day) and of
    // attendance.scheduling (Scheduling).
    to: paths.attendance,
    labelKey: 'nav.attendance',
    descriptionKey: 'home.attendanceDescription',
    icon: 'clock',
    anyOf: [{ roles: TRACKED_ROLES }, ...SCHEDULING_ACCESS, ...REQUESTS_ACCESS],
    children: [
      {
        to: paths.myAttendance,
        labelKey: 'nav.attendanceMe',
        descriptionKey: 'attendance.mine.description',
        icon: 'mapPin',
        roles: TRACKED_ROLES,
      },
      {
        to: paths.attendanceToday,
        labelKey: 'nav.attendanceToday',
        descriptionKey: 'attendance.today.description',
        icon: 'users',
        permission: 'attendance.view',
      },
      {
        // Tracked weekdays, holidays, shift times and rules: viewing with attendance.view,
        // editing with attendance.scheduling.
        to: paths.attendanceScheduling,
        labelKey: 'nav.attendanceScheduling',
        descriptionKey: 'attendance.scheduling.description',
        icon: 'calendar',
        anyOf: SCHEDULING_ACCESS,
      },
      {
        // The month's missing time (salary cut / unpaid extra work): tracked employees send a
        // request, holders of attendance.requests_review decide.
        to: paths.attendanceRequests,
        labelKey: 'nav.attendanceRequests',
        descriptionKey: 'attendance.requests.description',
        icon: 'clipboard',
        anyOf: REQUESTS_ACCESS,
        badge: 'pendingRequests',
      },
    ],
  },
  {
    to: paths.settings,
    labelKey: 'nav.settings',
    descriptionKey: 'home.settingsDescription',
    icon: 'settings',
    children: [
      {
        to: paths.users,
        labelKey: 'nav.users',
        descriptionKey: 'settings.usersDescription',
        icon: 'users',
        permission: 'users.view',
      },
      {
        to: paths.auditLogs,
        labelKey: 'nav.audit',
        descriptionKey: 'settings.auditDescription',
        icon: 'audit',
        // The superadmin holds it implicitly; a general manager only when the superadmin allows it.
        permission: 'audit.view',
      },
      {
        to: paths.userLimits,
        labelKey: 'nav.userLimits',
        descriptionKey: 'settings.userLimitsDescription',
        icon: 'sliders',
        roles: ROLE_LIMIT_ROLES,
      },
      {
        // The superadmin holds it implicitly; a general manager only when given Business info.
        to: paths.businessInfo,
        labelKey: 'nav.businessInfo',
        descriptionKey: 'business.description',
        icon: 'building',
        permission: 'settings.business_info',
      },
      {
        // Attendance workplaces: location and employees of each (the schedule is in Scheduling).
        to: paths.attendanceWorkplaces,
        labelKey: 'nav.attendanceWorkplaces',
        descriptionKey: 'attendance.workplaces.description',
        icon: 'mapPin',
        anyOf: WORKPLACE_ACCESS,
      },
      {
        to: paths.profile,
        labelKey: 'nav.profile',
        descriptionKey: 'settings.profileDescription',
        icon: 'user',
      },
    ],
  },
]

/**
 * Top-level items the user may see, each with only its visible children.
 * A section whose children are all filtered out is hidden, unless it is `keepWhenEmpty`
 * (or declared with `children: []`, "nothing in it yet").
 */
export function useNavItems(): NavItem[] {
  const canAccess = useCanAccess()
  return NAV_ITEMS.filter((item) => canAccess(item)).flatMap((item) => {
    if (!item.children || item.children.length === 0) return [item]
    const children = item.children.filter((child) => canAccess(child))
    return children.length > 0 || item.keepWhenEmpty ? [{ ...item, children }] : []
  })
}

/** Visible children of one top-level section (e.g. the Settings hub cards). */
export function useNavChildren(to: string): NavItem[] {
  return useNavItems().find((item) => item.to === to)?.children ?? []
}

