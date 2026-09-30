import type { NavBadgeKind, NavItem } from '@/layouts/nav'
import { usePendingPlanCount } from '@/pages/workstation/production-plans/api'

const COUNTS: Record<NavBadgeKind, () => number> = {
  pendingPlans: usePendingPlanCount,
}

function CountBadge({ kind }: { kind: NavBadgeKind }) {
  const count = COUNTS[kind]()
  if (count <= 0) return null
  return (
    <span className="ml-auto inline-flex min-w-5 items-center justify-center rounded-full bg-brand-600 px-1.5 text-xs font-semibold tabular-nums text-white">
      {count > 99 ? '99+' : count}
    </span>
  )
}

/** The item's count badge (sidebar, hub cards); nothing when it has none or the count is 0. */
export function NavBadge({ item }: { item: NavItem }) {
  return item.badge ? <CountBadge kind={item.badge} /> : null
}
