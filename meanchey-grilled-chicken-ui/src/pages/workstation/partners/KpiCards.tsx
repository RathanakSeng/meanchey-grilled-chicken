import { useTranslation } from 'react-i18next'
import { KpiGrid } from '@/components/KpiGrid'
import type { PartnerStats } from '@/lib/types'

export type PartnerStatus = 'active' | 'inactive' | 'all'

/** Active · New this month · Deactivated. Active and Deactivated also filter the list. */
export function KpiCards({
  stats,
  loading,
  status,
  onStatus,
}: {
  stats: PartnerStats | undefined
  loading: boolean
  status: PartnerStatus
  onStatus(status: PartnerStatus): void
}) {
  const { t } = useTranslation()
  return (
    <KpiGrid
      loading={loading}
      items={[
        {
          key: 'total_active',
          label: t('partners.kpi.active'),
          value: stats?.total_active,
          icon: 'check',
          tone: 'bg-green-50 text-green-700',
          selected: status === 'active',
          onClick: () => onStatus('active'),
        },
        {
          key: 'new_this_month',
          label: t('partners.kpi.newThisMonth'),
          value: stats?.new_this_month,
          icon: 'plus',
          tone: 'bg-brand-50 text-brand-600',
        },
        {
          key: 'inactive',
          label: t('partners.kpi.inactive'),
          value: stats?.inactive,
          icon: 'archive',
          tone: 'bg-stone-100 text-stone-600',
          selected: status === 'inactive',
          onClick: () => onStatus('inactive'),
        },
      ]}
    />
  )
}
