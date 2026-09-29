import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Icon } from '@/components/icons'
import { Sheet } from '@/components/Sheet'
import { Badge, EmptyState, Input, Spinner, cx } from '@/components/ui'
import { api } from '@/lib/api'
import type { SupplierOption } from '@/lib/types'
import { useDebounced } from '@/lib/useDebounced'
import { productionKeys } from './api'
import type { RawValues } from './steps'

/**
 * Pick the supplier of a batch from the active suppliers (`/production/supplier-options`), so
 * workers don't need access to the Suppliers page. A searchable list in a sheet.
 */
export function SupplierPicker({
  value,
  onChange,
  invalid,
}: {
  value: RawValues['supplier']
  onChange(value: SupplierOption): void
  invalid?: boolean
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const search = useDebounced(q.trim())
  const options = useQuery({
    queryKey: productionKeys.supplierOptions(search),
    queryFn: async () =>
      (
        await api.get<SupplierOption[]>('/production/supplier-options', {
          params: { q: search || undefined },
        })
      ).data,
    enabled: open,
  })

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cx(
          'flex min-h-12 w-full items-center justify-between gap-2 rounded-lg bg-white px-3 py-2 text-left shadow-sm ring-1 ring-inset sm:min-h-10',
          invalid ? 'ring-red-400' : 'ring-stone-300 hover:ring-stone-400',
        )}
      >
        {value ? (
          <span className="min-w-0">
            <span className="flex flex-wrap items-center gap-2 font-medium text-stone-900">
              {value.name}
              {value.is_active === false && <Badge tone="amber">{t('production.supplierInactive')}</Badge>}
            </span>
            {value.phone_display && (
              <span className="block text-xs tabular-nums text-stone-500">{value.phone_display}</span>
            )}
          </span>
        ) : (
          <span className="text-stone-400">{t('production.chooseSupplier')}</span>
        )}
        <Icon name="chevronRight" width={18} height={18} className="shrink-0 text-stone-400" />
      </button>

      <Sheet open={open} title={t('production.chooseSupplier')} onClose={() => setOpen(false)}>
        <div className="relative mb-3">
          <Icon
            name="search"
            width={16}
            height={16}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-400"
          />
          <Input
            type="search"
            autoFocus
            className="h-12 pl-9 text-base sm:h-10 sm:text-sm"
            placeholder={t('production.searchSupplier')}
            aria-label={t('common.search')}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        {options.isPending ? (
          <div className="flex justify-center py-8 text-brand-600">
            <Spinner />
          </div>
        ) : options.data && options.data.length > 0 ? (
          <ul className="-mx-2 divide-y divide-stone-100">
            {options.data.map((o) => (
              <li key={o.id}>
                <button
                  type="button"
                  onClick={() => {
                    onChange(o)
                    setOpen(false)
                  }}
                  className={cx(
                    'flex w-full items-center justify-between gap-2 rounded-lg px-2 py-3 text-left hover:bg-stone-50',
                    value?.id === o.id && 'bg-brand-50',
                  )}
                >
                  <span className="min-w-0">
                    <span className="block font-medium text-stone-900">{o.name}</span>
                    {o.phone_display && (
                      <span className="block text-xs tabular-nums text-stone-500">{o.phone_display}</span>
                    )}
                  </span>
                  {value?.id === o.id && <Icon name="check" className="text-brand-600" />}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState>{t('production.noSuppliers')}</EmptyState>
        )}
      </Sheet>
    </>
  )
}
