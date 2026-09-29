import { useTranslation } from 'react-i18next'
import { KpiGrid } from '@/components/KpiGrid'
import type { PartnerStats } from '@/lib/types'

/** Active · New this month · Deactivated (figures only; "Show deactivated" filters the list). */
export function KpiCards({ stats, loading }: { stats: PartnerStats | undefined; loading: boolean }) {
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
        },
      ]}
    />
  )
}
