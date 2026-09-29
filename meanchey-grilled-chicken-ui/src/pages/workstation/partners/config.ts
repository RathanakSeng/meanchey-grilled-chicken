import type { IconName } from '@/components/icons'
import { paths } from '@/lib/paths'
import type { PartnerEntityType } from '@/lib/types'

/**
 * Everything that differs between the partner lists. `PartnerListPage` is generic; a new list
 * with the same shape (name, location, phone) only needs a config, a route and translations.
 */
export interface PartnerConfig {
  /** API collection path, also the permission prefix and the i18n namespace: `suppliers`. */
  resource: 'suppliers' | 'customers'
  /** Singular: audit entity type and the single-record query key. */
  entity: PartnerEntityType
  /** Frontend route of the list page. */
  path: string
  icon: IconName
}

export const SUPPLIERS: PartnerConfig = {
  resource: 'suppliers',
  entity: 'supplier',
  path: paths.suppliers,
  icon: 'truck',
}

export const CUSTOMERS: PartnerConfig = {
  resource: 'customers',
  entity: 'customer',
  path: paths.customers,
  icon: 'store',
}

export const PARTNER_CONFIGS: Record<PartnerEntityType, PartnerConfig> = {
  supplier: SUPPLIERS,
  customer: CUSTOMERS,
}

/** Query keys: ['suppliers', params], ['suppliers-stats'], ['supplier', id]. */
export function partnerKeys(config: PartnerConfig) {
  return {
    list: [config.resource] as const,
    stats: [`${config.resource}-stats`] as const,
    one: (id: string) => [config.entity, id] as const,
  }
}

export function permission(config: PartnerConfig, action: 'view' | 'create' | 'update' | 'delete') {
  return `${config.resource}.${action}`
}

/** Link to a list with the search box prefilled, deactivated records included (audit log). */
export function partnerSearchLink(config: PartnerConfig, q: string) {
  return `${config.path}?${new URLSearchParams({ q, deactivated: '1' })}`
}
