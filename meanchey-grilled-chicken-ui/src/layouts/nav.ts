import { useCanAccess, type AccessRule } from '@/auth/usePermission'
import type { IconName } from '@/components/icons'
import { paths } from '@/lib/paths'
import { AUDIT_ROLES } from '@/lib/roles'

export type NavBadgeKind = 'pendingPlans'

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
        roles: AUDIT_ROLES,
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

