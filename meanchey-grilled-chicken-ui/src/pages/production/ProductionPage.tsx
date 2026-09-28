import { useTranslation } from 'react-i18next'
import { Icon } from '@/components/icons'
import { Card, PageHeader } from '@/components/ui'
import { paths } from '@/lib/paths'

/** Production section. Empty until the first production features land (add them in nav.ts). */
export function ProductionPage() {
  const { t } = useTranslation()
  return (
    <>
      <PageHeader title={t('nav.production')} back={paths.home} />
      <Card>
        <div className="flex flex-col items-center py-10 text-center">
          <span className="mb-4 inline-flex h-14 w-14 items-center justify-center rounded-full bg-brand-50 text-brand-600">
            <Icon name="flame" width={28} height={28} />
          </span>
          <h2 className="text-base font-semibold text-stone-900">{t('production.emptyTitle')}</h2>
          <p className="mt-1 max-w-sm text-sm text-stone-500">{t('production.emptyBody')}</p>
        </div>
      </Card>
    </>
  )
}
