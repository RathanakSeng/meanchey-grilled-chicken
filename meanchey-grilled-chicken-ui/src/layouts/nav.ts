import { useCanAccess, type AccessRule } from '@/auth/usePermission'
import type { IconName } from '@/components/icons'
import { paths } from '@/lib/paths'

export interface NavItem extends AccessRule {
  to: string
  labelKey: string
  /** One-line description, shown on the Home tiles and the Settings hub cards. */
  descriptionKey?: string
  icon: IconName
  /** Match only the exact path when highlighting (used for Home). */
  end?: boolean
  children?: NavItem[]
}

/**
 * The app menu, as a tree. Items render only when the user passes their `permission` / `roles`
 * rule; a parent with children is shown only if at least one child is visible.
 *
 * New feature? Add a child under Production or Settings (or a new top-level item) with the
 * permission that guards its route. Home, the sidebar, the bottom nav and the Settings hub all
 * read from this tree.
 */
export const NAV_ITEMS: NavItem[] = [
  { to: paths.home, labelKey: 'nav.home', icon: 'home', end: true },
  {
    to: paths.production,
    labelKey: 'nav.production',
    descriptionKey: 'home.productionDescription',
    icon: 'flame',
    children: [],
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
        roles: ['superadmin', 'general_manager'],
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
 * An empty `children: []` (Production today) means "a section with nothing in it yet" and stays
 * visible; a section whose children are all filtered out is hidden.
 */
export function useNavItems(): NavItem[] {
  const canAccess = useCanAccess()
  return NAV_ITEMS.filter((item) => canAccess(item)).flatMap((item) => {
    if (!item.children || item.children.length === 0) return [item]
    const children = item.children.filter((child) => canAccess(child))
    return children.length > 0 ? [{ ...item, children }] : []
  })
}

/** Visible children of one top-level section (e.g. the Settings hub cards). */
export function useNavChildren(to: string): NavItem[] {
  return useNavItems().find((item) => item.to === to)?.children ?? []
}
