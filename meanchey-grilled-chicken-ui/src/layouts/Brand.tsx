import { useTranslation } from 'react-i18next'
import { Icon } from '@/components/icons'

export function Brand({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation()
  return (
    <div className="flex min-w-0 items-center gap-2.5">
      <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-600 text-white">
        <Icon name="chicken" width={20} height={20} />
      </span>
      <div className="min-w-0 leading-tight">
        <p className="truncate text-sm font-semibold text-stone-900">{t('app.name')}</p>
        {!compact && <p className="truncate text-xs text-stone-500">{t('app.tagline')}</p>}
      </div>
    </div>
  )
}
