import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { Alert, Badge, Button, Card, Field, Input, PageHeader, Spinner, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useFormatDate, useLocalized } from '@/lib/format'
import { paths } from '@/lib/paths'
import { useQuantityFormat } from '@/lib/quantity'
import type { InventoryClear, InventoryClearLine, Page } from '@/lib/types'
import { inventoryKeys } from './api'
import { ImpactList, useImpactSummary } from './ClearSheet'

const PAGE_SIZE = 50

/** "4-Piece Packs 20 → Wasted" / "String 1.500 kg · removed". */
function useLineText() {
  const { t } = useTranslation()
  const localized = useLocalized()
  const format = useQuantityFormat()
  return (line: InventoryClearLine) => {
    const name =
      line.section === 'wasted' || line.section === 'prepared'
        ? `${t(`inventory.sections.${line.section}`)}: ${localized(line)}`
        : localized(line)
    const kg = line.kg ? ` (${line.kg_estimated ? '≈ ' : ''}${format(line.kg, 'kg')})` : ''
    return { name, amount: `${format(line.quantity, line.unit)}${kg}` }
  }
}

/**
 * History → Clears: the clear records, newest first (inventory.history or inventory.clear), with
 * a date range; each opens its record.
 */
export function ClearsList() {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const formatDate = useFormatDate()
  const lineText = useLineText()
  const [searchParams, setSearchParams] = useSearchParams()
  const get = (k: string) => searchParams.get(k) ?? ''
  const page = Math.max(1, Number(searchParams.get('page')) || 1)
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
  const params = {
    date_from: get('from') || undefined,
    date_to: get('to') || undefined,
    page,
    page_size: PAGE_SIZE,
  }
  const list = useQuery({
    queryKey: inventoryKeys.clears(params),
    queryFn: async () => (await api.get<Page<InventoryClear>>('/inventory/clears', { params })).data,
    placeholderData: keepPreviousData,
  })
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / PAGE_SIZE)) : 1

  return (
    <>
      <div className="mb-4 grid grid-cols-2 gap-2 sm:max-w-md">
        <Field label={t('inventory.filters.from')}>
          {(id) => <Input id={id} type="date" value={get('from')} onChange={(e) => update({ from: e.target.value })} />}
        </Field>
        <Field label={t('inventory.filters.to')}>
          {(id) => <Input id={id} type="date" value={get('to')} onChange={(e) => update({ to: e.target.value })} />}
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
            <p className="py-6 text-center text-sm text-stone-500">{t('inventory.clear.none')}</p>
          </Card>
        ) : (
          <ul
            className={cx(
              'divide-y divide-stone-100 rounded-xl bg-white shadow-sm ring-1 ring-stone-200',
              list.isPlaceholderData && 'opacity-60',
            )}
          >
            {list.data.items.map((c) => (
              <li key={c.id}>
                <Link to={paths.inventoryClear(c.id)} className="block px-4 py-3 hover:bg-stone-50">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium tabular-nums text-brand-700">{c.code}</span>
                    {c.impacts.length > 0 && <Badge tone="red">{t('inventory.clear.withImpacts')}</Badge>}
                  </div>
                  <p className="text-sm text-stone-700">
                    {c.lines
                      .map((line) => {
                        const { name, amount } = lineText(line)
                        return `${name} ${amount}`
                      })
                      .join(', ')}
                  </p>
                  <p className="truncate text-sm text-stone-500">“{c.reason}”</p>
                  <p className="text-xs text-stone-400">
                    {formatDate(c.created_at)} ·{' '}
                    {c.created_by && !c.created_by.is_system ? c.created_by.full_name : t('audit.system')}
                  </p>
                </Link>
              </li>
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

/** One clear (`/workstation/inventory/clears/:id`): lines, reason, the impacts acknowledged, who / when. */
export function ClearDetailPage() {
  const { t } = useTranslation()
  const { id = '' } = useParams()
  const errorMessage = useErrorMessage()
  const formatDate = useFormatDate()
  const lineText = useLineText()
  const summary = useImpactSummary()
  const clear = useQuery({
    queryKey: inventoryKeys.clear(id),
    queryFn: async () => (await api.get<InventoryClear>(`/inventory/clears/${id}`)).data,
  })
  const c = clear.data

  return (
    <>
      <PageHeader
        back={paths.inventoryClears}
        title={c ? c.code : t('inventory.clear.recordTitle')}
        subtitle={t('inventory.clear.recordSubtitle')}
      />
      {clear.isError && <Alert tone="error">{errorMessage(clear.error)}</Alert>}
      {clear.isPending && (
        <div className="flex justify-center py-10 text-brand-600">
          <Spinner />
        </div>
      )}
      {c && (
        <div className="space-y-4">
          <Card>
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-stone-500">{t('inventory.clear.by')}</dt>
                <dd className="font-medium text-stone-900">
                  {c.created_by && !c.created_by.is_system ? c.created_by.full_name : t('audit.system')}
                </dd>
              </div>
              <div>
                <dt className="text-stone-500">{t('inventory.clear.when')}</dt>
                <dd className="font-medium text-stone-900">{formatDate(c.created_at)}</dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-stone-500">{t('inventory.clear.reason')}</dt>
                <dd className="whitespace-pre-wrap text-stone-900">{c.reason}</dd>
              </div>
            </dl>
          </Card>
          <Card title={t('inventory.clear.items')}>
            <ul className="-my-2 divide-y divide-stone-100">
              {c.lines.map((line) => {
                const { name, amount } = lineText(line)
                return (
                  <li key={line.item_code} className="flex flex-wrap items-baseline justify-between gap-2 py-2">
                    <span className="font-medium text-stone-900">{name}</span>
                    <span className="text-sm tabular-nums text-stone-700">
                      −{amount}{' '}
                      <span className={line.moved_to ? 'text-red-700' : 'text-stone-500'}>
                        {line.moved_to ? t('inventory.clear.toWasted') : t('inventory.clear.removed')}
                      </span>
                    </span>
                  </li>
                )
              })}
            </ul>
          </Card>
          <Card title={t('inventory.clear.impactsTitle')}>
            {c.impacts.length === 0 ? (
              <p className="text-sm text-stone-500">{t('inventory.clear.noImpactsRecorded')}</p>
            ) : (
              <>
                <p className="mb-3 text-sm font-medium text-red-800">
                  {t('inventory.clear.acknowledgedSummary', { list: summary(c.impacts) })}
                </p>
                <ImpactList impacts={c.impacts} />
              </>
            )}
          </Card>
          <p className="text-xs text-stone-500">{t('inventory.clear.noUndo')}</p>
        </div>
      )}
    </>
  )
}
