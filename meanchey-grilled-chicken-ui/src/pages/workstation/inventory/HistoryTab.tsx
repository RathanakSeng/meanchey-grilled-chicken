import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { Alert, Button, Card, Field, Input, Select, Spinner, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useLocalized } from '@/lib/format'
import type { InventoryItem, InventoryMovement, Page } from '@/lib/types'
import { useDebounced } from '@/lib/useDebounced'
import { inventoryKeys } from './api'
import { MovementRow } from './MovementRow'

const PAGE_SIZE = 50
// `area` (stock / wasted), not `section`: that one is the Stock tab's sub-tab, kept in the URL.
const FILTERS = ['item', 'area', 'source', 'from', 'to', 'batch'] as const

/**
 * Movements, newest first. Filters (kept in the URL with `tab=history`): item, section (`area`), type
 * (production / adjustment), date range (business days) and part of a batch code.
 */
export function HistoryTab({ items }: { items: InventoryItem[] }) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const errorMessage = useErrorMessage()
  const [searchParams, setSearchParams] = useSearchParams()
  const get = (k: (typeof FILTERS)[number]) => searchParams.get(k) ?? ''
  const page = Math.max(1, Number(searchParams.get('page')) || 1)
  const [batch, setBatch] = useState(get('batch'))
  const batchSearch = useDebounced(batch.trim())

  const update = (changes: Record<string, string | null>) =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [k, v] of Object.entries(changes)) {
          if (v === null || v === '') next.delete(k)
          else next.set(k, v)
        }
        if (!('page' in changes)) next.delete('page')
        return next
      },
      { replace: true },
    )
  useEffect(() => {
    if (batchSearch !== get('batch')) update({ batch: batchSearch || null })
  }, [batchSearch])

  const params = {
    item_code: get('item') || undefined,
    section: get('area') || undefined,
    source: get('source') || undefined,
    date_from: get('from') || undefined,
    date_to: get('to') || undefined,
    batch_code: get('batch') || undefined,
    page,
    page_size: PAGE_SIZE,
  }
  const list = useQuery({
    queryKey: [...inventoryKeys.movements, params],
    queryFn: async () =>
      (await api.get<Page<InventoryMovement>>('/inventory/movements', { params })).data,
    placeholderData: keepPreviousData,
  })
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / PAGE_SIZE)) : 1
  const filtered = FILTERS.some((k) => get(k))

  return (
    <>
      <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Field label={t('inventory.filters.item')}>
          {(id) => (
            <Select id={id} value={get('item')} onChange={(e) => update({ item: e.target.value })}>
              <option value="">{t('inventory.filters.all')}</option>
              {items.map((i) => (
                <option key={i.code} value={i.code}>
                  {i.section === 'wasted' ? `${t('inventory.sections.wasted')}: ` : ''}
                  {localized(i)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('inventory.filters.section')}>
          {(id) => (
            <Select id={id} value={get('area')} onChange={(e) => update({ area: e.target.value })}>
              <option value="">{t('inventory.filters.all')}</option>
              <option value="stock">{t('inventory.sections.stock')}</option>
              <option value="wasted">{t('inventory.sections.wasted')}</option>
            </Select>
          )}
        </Field>
        <Field label={t('inventory.filters.type')}>
          {(id) => (
            <Select id={id} value={get('source')} onChange={(e) => update({ source: e.target.value })}>
              <option value="">{t('inventory.filters.all')}</option>
              <option value="production">{t('inventory.sources.production')}</option>
              <option value="adjustment">{t('inventory.sources.adjustment')}</option>
            </Select>
          )}
        </Field>
        <Field label={t('inventory.filters.from')}>
          {(id) => (
            <Input id={id} type="date" value={get('from')} onChange={(e) => update({ from: e.target.value })} />
          )}
        </Field>
        <Field label={t('inventory.filters.to')}>
          {(id) => (
            <Input id={id} type="date" value={get('to')} onChange={(e) => update({ to: e.target.value })} />
          )}
        </Field>
        <Field label={t('inventory.filters.batch')}>
          {(id) => (
            <Input
              id={id}
              type="search"
              placeholder="PR-…"
              value={batch}
              onChange={(e) => setBatch(e.target.value)}
            />
          )}
        </Field>
      </div>

      {list.isError && <Alert tone="error">{errorMessage(list.error)}</Alert>}
      {list.isPending && (
        <div className="flex justify-center py-10 text-brand-600">
          <Spinner />
        </div>
      )}
      {list.data &&
        (list.data.items.length === 0 ? (
          <Card>
            <p className="py-6 text-center text-sm text-stone-500">
              {t(filtered ? 'inventory.noMovementsFiltered' : 'inventory.noMovements')}
            </p>
            {filtered && (
              <div className="text-center">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setBatch('')
                    update(Object.fromEntries(FILTERS.map((k) => [k, null])))
                  }}
                >
                  {t('partners.clearFilters')}
                </Button>
              </div>
            )}
          </Card>
        ) : (
          <ul
            className={cx(
              'divide-y divide-stone-100 rounded-xl bg-white shadow-sm ring-1 ring-stone-200',
              list.isPlaceholderData && 'opacity-60',
            )}
          >
            {list.data.items.map((m) => (
              <MovementRow key={m.id} movement={m} />
            ))}
          </ul>
        ))}

      {list.data && pages > 1 && (
        <div className="mt-4 flex items-center justify-between gap-2 text-sm text-stone-600">
          <Button variant="secondary" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}>
            {t('common.previous')}
          </Button>
          <span>{t('common.pageOf', { page, pages })}</span>
          <Button variant="secondary" disabled={page >= pages} onClick={() => update({ page: String(page + 1) })}>
            {t('common.next')}
          </Button>
        </div>
      )}
    </>
  )
}
