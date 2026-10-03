import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import { usePermission } from '@/auth/usePermission'
import { ActionMenu, type ActionMenuItem } from '@/components/ActionMenu'
import { Icon } from '@/components/icons'
import { Sheet } from '@/components/Sheet'
import { Alert, Button, Card, ConfirmDialog, Field, PageHeader, Spinner, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { getError, useErrorMessage } from '@/lib/errors'
import { useFormatDate, useFormatDay, useLocalized } from '@/lib/format'
import { paths } from '@/lib/paths'
import { fetchPdf, printPdf, tabForPdf } from '@/lib/pdf'
import { isTelegramMiniApp } from '@/lib/telegram'
import { ORDER_REASON_MAX_LENGTH, type DocumentSent, type Order, type UserRef } from '@/lib/types'
import { amountOf, invalidateOrders, orderKeys, useAmountFormat, useQuantityFormat } from './api'
import { BoxColorLabel, OrderStatusBadge } from './badges'
import { DeliveredSheet, ReviewSheet, type DeliveredBody, type ReviewBody } from './OrderSheets'
import { OrderSummaryView, fromApi } from './OrderSummaryView'

function useByName() {
  const { t } = useTranslation()
  return (user: UserRef | null) => (user && !user.is_system ? user.full_name : t('audit.system'))
}

interface TimelineStep {
  key: string
  label: string
  at: string | null
  by: UserRef | null
  tone: 'done' | 'current' | 'todo' | 'bad'
}

/** Created → Delivering → Delivered → (Return pending → Reviewed), or Created → Cancelled. */
function Timeline({ order }: { order: Order }) {
  const { t } = useTranslation()
  const formatDate = useFormatDate()
  const byName = useByName()
  const s = order.status
  const returned = order.returns.length > 0
  const steps: TimelineStep[] = [
    { key: 'created', label: t('orders.timeline.created'), at: order.created_at, by: order.created_by, tone: 'done' },
  ]
  if (s === 'cancelled') {
    steps.push({
      key: 'cancelled',
      label: t('orders.timeline.cancelled'),
      at: order.cancelled_at,
      by: order.cancelled_by,
      tone: 'bad',
    })
  } else {
    steps.push(
      {
        key: 'delivering',
        label: t('orders.timeline.delivering'),
        at: order.delivering_at,
        by: order.delivering_by,
        tone: order.delivering_at ? 'done' : 'todo',
      },
      {
        key: 'delivered',
        label: t(returned ? 'orders.timeline.deliveredReturned' : 'orders.timeline.delivered'),
        at: order.delivered_at,
        by: order.delivered_by,
        tone: order.delivered_at ? 'done' : s === 'delivering' ? 'current' : 'todo',
      },
    )
    if (returned) {
      steps.push({
        key: 'reviewed',
        label: t('orders.timeline.reviewed'),
        at: order.returns_reviewed_at,
        by: order.returns_reviewed_by,
        tone: order.returns_reviewed_at ? 'done' : 'current',
      })
    }
  }
  return (
    <ol className="space-y-3">
      {steps.map((step) => (
        <li key={step.key} className="flex items-start gap-3">
          <span
            className={cx(
              'mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full',
              step.tone === 'done' && 'bg-green-600 text-white',
              step.tone === 'current' && 'bg-amber-100 text-amber-700 ring-2 ring-amber-400',
              step.tone === 'todo' && 'bg-stone-100 text-stone-400',
              step.tone === 'bad' && 'bg-red-600 text-white',
            )}
          >
            {step.tone === 'done' ? (
              <Icon name="check" width={14} height={14} />
            ) : step.tone === 'bad' ? (
              <Icon name="close" width={14} height={14} />
            ) : (
              <span className="h-1.5 w-1.5 rounded-full bg-current" />
            )}
          </span>
          <span className="min-w-0">
            <span className={cx('block text-sm font-medium', step.tone === 'todo' ? 'text-stone-400' : 'text-stone-900')}>
              {step.label}
            </span>
            {step.at && (
              <span className="block text-xs text-stone-500">
                {formatDate(step.at)} · {byName(step.by)}
              </span>
            )}
          </span>
        </li>
      ))}
    </ol>
  )
}

function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:gap-3">
      <dt className="w-32 shrink-0 text-sm text-stone-500">{label}</dt>
      <dd className="min-w-0 text-sm text-stone-900">{children}</dd>
    </div>
  )
}

/** What came back, why, and (after the review) where it went. */
function ReturnsCard({ order }: { order: Order }) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const format = useAmountFormat()
  if (order.returns.length === 0) return null
  const reviewed = order.returns_reviewed_at !== null
  return (
    <Card title={t('orders.returns')}>
      {order.return_reason && (
        <p className="mb-3 text-sm text-stone-700">{t('orders.reasonQuoted', { reason: order.return_reason })}</p>
      )}
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="text-left text-xs font-semibold uppercase tracking-wide text-stone-500">
            <tr>
              <th className="py-1.5 pr-3">{t('orders.item')}</th>
              <th className="px-3 py-1.5 text-right">{t('orders.delivered')}</th>
              <th className="px-3 py-1.5 text-right">{t('orders.returned')}</th>
              {reviewed && <th className="px-3 py-1.5 text-right">{t('orders.backToStock')}</th>}
              {reviewed && <th className="py-1.5 pl-3 text-right">{t('orders.wasted')}</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {order.returns.map((r) => (
              <tr key={r.item_code}>
                <td className="py-2 pr-3 text-stone-800">{localized(r)}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {format(r.unit, amountOf({ count: r.delivered_count, kg: r.delivered_kg }))}
                </td>
                <td className="px-3 py-2 text-right font-medium tabular-nums">
                  {format(r.unit, amountOf({ count: r.returned_count, kg: r.returned_kg }))}
                </td>
                {reviewed && (
                  <td className="px-3 py-2 text-right tabular-nums text-green-700">
                    {format(r.unit, amountOf({ count: r.to_stock_count, kg: r.to_stock_kg }))}
                  </td>
                )}
                {reviewed && (
                  <td className="py-2 pl-3 text-right tabular-nums text-red-700">
                    {format(r.unit, amountOf({ count: r.to_wasted_count, kg: r.to_wasted_kg }))}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!reviewed && <p className="mt-3 text-sm text-amber-800">{t('orders.waitingReview')}</p>}
    </Card>
  )
}

/**
 * One order: header (code, status, ⋮ Edit / Cancel while Created), customer, delivery date,
 * driver and note, the action for its status (Start delivery · Mark delivered · Review return),
 * the status timeline, the per-colour summary, the boxes and the returns.
 */
export function OrderPage() {
  const { t } = useTranslation()
  const { orderId = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const formatDay = useFormatDay()
  const formatQty = useQuantityFormat()
  const localized = useLocalized()
  const byName = useByName()
  const canRecord = usePermission('orders.create')
  const canEdit = usePermission('orders.update')
  const canCancel = usePermission('orders.cancel')
  const canReview = usePermission('orders.review_returns')

  const query = useQuery({
    queryKey: orderKeys.order(orderId),
    queryFn: async () => (await api.get<Order>(`/orders/${orderId}`)).data,
  })
  const order = query.data

  const [sheet, setSheet] = useState<'delivering' | 'delivered' | 'review' | 'cancel' | null>(null)
  const [reason, setReason] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const [docResult, setDocResult] = useState<{ tone: 'success' | 'error'; text: string } | null>(null)

  const onSaved = (o: Order) => {
    queryClient.setQueryData(orderKeys.order(o.id), o)
    invalidateOrders(queryClient)
    setSheet(null)
  }
  const onError = (err: unknown) => {
    const { code, details } = getError(err)
    if (code === 'ORDER_CONFLICT' || code === 'ORDER_INVALID_STATUS') {
      // Someone else moved the order on: show the current one.
      if (details.order) queryClient.setQueryData(orderKeys.order(orderId), details.order as Order)
      else void queryClient.invalidateQueries({ queryKey: orderKeys.order(orderId) })
      invalidateOrders(queryClient)
      setSheet(null)
      setNotice(t('orders.conflictReloaded'))
    }
  }
  const action = useMutation({
    mutationFn: async ({ path, body }: { path: string; body: object }) =>
      (await api.post<Order>(`/orders/${orderId}/${path}`, { version: order?.version, ...body })).data,
    onSuccess: onSaved,
    onError,
  })
  const run = (path: string, body: object = {}) => {
    setNotice(null)
    action.mutate({ path, body })
  }
  // Delivery note: printed (PC / phone browser) or sent to the requester's Telegram chat (Mini App).
  // Each one is counted by the API (the next one says COPY), so the order is refetched.
  const refreshCount = () => void queryClient.invalidateQueries({ queryKey: orderKeys.order(orderId) })
  const print = useMutation({
    mutationFn: (tab: Window | null) => printPdf(() => fetchPdf(`/orders/${orderId}/document.pdf`), tab),
    onMutate: () => setDocResult(null),
    onSuccess: refreshCount,
    onError: (err) => setDocResult({ tone: 'error', text: errorMessage(err) }),
  })
  const sendToTelegram = useMutation({
    mutationFn: async () => (await api.post<DocumentSent>(`/orders/${orderId}/document/send-telegram`)).data,
    onMutate: () => setDocResult(null),
    onSuccess: () => {
      refreshCount()
      setDocResult({ tone: 'success', text: t('orders.document.sent') })
    },
    onError: (err) => setDocResult({ tone: 'error', text: errorMessage(err) }),
  })

  const open = (which: typeof sheet) => {
    action.reset()
    setReason(t('orders.cancelReasonDefault'))
    setSheet(which)
  }

  if (query.isPending) {
    return (
      <div className="flex justify-center py-16 text-brand-600">
        <Spinner />
      </div>
    )
  }
  if (!order) {
    return (
      <>
        <PageHeader back={paths.orders} title={t('orders.title')} />
        <Alert tone="error">{errorMessage(query.error)}</Alert>
      </>
    )
  }

  const created = order.status === 'created'
  const menu: ActionMenuItem[] = [
    // Outside the Mini App, sending to Telegram is the secondary way to get the note.
    ...(!isTelegramMiniApp
      ? [
          {
            key: 'send-telegram',
            label: t('orders.document.sendTelegram'),
            icon: 'telegram' as const,
            onSelect: () => sendToTelegram.mutate(),
          },
        ]
      : []),
    ...(created && canEdit
      ? [{ key: 'edit', label: t('common.edit'), icon: 'pencil' as const, onSelect: () => navigate(paths.editOrder(order.id)) }]
      : []),
    ...(created && canCancel
      ? [
          {
            key: 'cancel',
            label: t('orders.cancelOrder'),
            icon: 'archive' as const,
            tone: 'danger' as const,
            onSelect: () => open('cancel'),
          },
        ]
      : []),
  ]

  const primary =
    created && canRecord ? (
      <Button onClick={() => open('delivering')}>
        <Icon name="truck" width={18} height={18} />
        {t('orders.startDelivery')}
      </Button>
    ) : order.status === 'delivering' && canRecord ? (
      <Button onClick={() => open('delivered')}>
        <Icon name="check" width={18} height={18} />
        {t('orders.markDelivered')}
      </Button>
    ) : order.status === 'return_pending' && canReview ? (
      <Button onClick={() => open('review')}>
        <Icon name="restore" width={18} height={18} />
        {t('orders.reviewReturn')}
      </Button>
    ) : null

  const sheetError = action.isError && !['ORDER_CONFLICT', 'ORDER_INVALID_STATUS'].includes(getError(action.error).code)
    ? errorMessage(action.error)
    : null

  return (
    <>
      <PageHeader
        back={paths.orders}
        title={<span className="tabular-nums">{order.code}</span>}
        subtitle={
          <span className="flex flex-wrap items-center gap-1.5">
            <OrderStatusBadge status={order.status} />
            <span>{order.customer.name}</span>
          </span>
        }
        actions={
          <>
            {primary && <span className="hidden sm:inline-flex">{primary}</span>}
            {/* Printing isn't reliable inside Telegram: there the note is sent to the chat. */}
            {isTelegramMiniApp ? (
              <Button
                variant="secondary"
                loading={sendToTelegram.isPending}
                onClick={() => sendToTelegram.mutate()}
                title={t('orders.document.sendTelegram')}
              >
                {!sendToTelegram.isPending && <Icon name="telegram" width={18} height={18} />}
                <span className="hidden min-[400px]:inline">{t('orders.document.sendTelegramShort')}</span>
              </Button>
            ) : (
              <Button
                variant="secondary"
                loading={print.isPending}
                onClick={() => print.mutate(tabForPdf())}
                title={t('orders.document.printHint')}
              >
                {!print.isPending && <Icon name="printer" width={18} height={18} />}
                <span className="hidden min-[400px]:inline">{t('orders.document.print')}</span>
              </Button>
            )}
            <ActionMenu items={menu} label={t('orders.actions')} />
          </>
        }
      />

      {docResult && (
        <Alert tone={docResult.tone} className="mb-4">
          {docResult.text}
        </Alert>
      )}

      {notice && (
        <Alert tone="warning" className="mb-4">
          {notice}
        </Alert>
      )}
      {order.status === 'cancelled' && (
        <Alert tone="warning" className="mb-4">
          <p className="font-medium">{t('orders.cancelledNotice')}</p>
          {order.cancel_reason && <p className="mt-0.5">{order.cancel_reason}</p>}
        </Alert>
      )}
      {order.status === 'return_pending' && !canReview && (
        <Alert className="mb-4">{t('orders.waitingReview')}</Alert>
      )}
      {order.stock_warnings.length > 0 && (
        <Alert tone="warning" className="mb-4">
          <p className="font-medium">{t('orders.stockWarningTitle')}</p>
          <ul className="mt-1 space-y-0.5">
            {order.stock_warnings.map((w) => (
              <li key={w.item_code}>
                {t('orders.onlyInStock', {
                  amount: formatQty({ ...w, count: w.available_count, kg: w.available_kg }),
                  name: localized(w),
                })}
              </li>
            ))}
          </ul>
        </Alert>
      )}
      {/* Phones: the action as a full-width button under the header. */}
      {primary && <div className="mb-4 grid sm:hidden">{primary}</div>}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="space-y-4">
          <Card>
            <dl className="space-y-2">
              <InfoRow label={t('orders.fields.customer')}>
                <span className="font-medium">{order.customer.name}</span>
                {order.customer.phone_display && (
                  <a href={`tel:${order.customer.phone_display.replace(/\s+/g, '')}`} className="ml-2 tabular-nums text-brand-700 hover:underline">
                    {order.customer.phone_display}
                  </a>
                )}
                {order.customer.location && <span className="block text-stone-500">{order.customer.location}</span>}
              </InfoRow>
              <InfoRow label={t('orders.fields.deliveryDate')}>{formatDay(order.delivery_date)}</InfoRow>
              <InfoRow label={t('orders.fields.driver')}>
                {order.driver ? byName(order.driver) : <span className="text-stone-400">{t('orders.noDriver')}</span>}
              </InfoRow>
              {order.print_count > 0 && (
                <InfoRow label={t('orders.document.title')}>
                  {t('orders.document.printedCount', { count: order.print_count })}
                </InfoRow>
              )}
              {order.note && (
                <InfoRow label={t('orders.fields.note')}>
                  <span className="whitespace-pre-line">{order.note}</span>
                </InfoRow>
              )}
            </dl>
          </Card>

          <ReturnsCard order={order} />

          <Card title={t('orders.boxesTitle', { count: order.boxes.length })}>
            <ul className="divide-y divide-stone-100">
              {order.boxes.map((box) => (
                <li key={box.id} className="py-2.5 first:pt-0 last:pb-0">
                  <p className="mb-1 flex items-center gap-2 text-sm font-medium text-stone-900">
                    {t('orders.boxTitle', { n: box.position })}
                    <span className="font-normal text-stone-500">
                      <BoxColorLabel color={box.color} />
                    </span>
                  </p>
                  <ul className="space-y-0.5 text-sm">
                    {box.lines.map((line) => (
                      <li key={line.item_code} className="flex justify-between gap-3 text-stone-700">
                        <span>{localized(line)}</span>
                        <span className="tabular-nums">{formatQty(line)}</span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        <div className="space-y-4">
          <Card title={t('orders.summary')}>
            <OrderSummaryView summary={fromApi(order.summary)} />
          </Card>
          <Card title={t('orders.timeline.title')}>
            <Timeline order={order} />
          </Card>
        </div>
      </div>

      <ConfirmDialog
        open={sheet === 'delivering'}
        title={t('orders.startDeliveryTitle', { code: order.code })}
        body={t('orders.startDeliveryBody', { boxes: order.boxes.length, customer: order.customer.name })}
        confirmLabel={t('orders.startDelivery')}
        loading={action.isPending}
        error={sheetError}
        onConfirm={() => run('delivering')}
        onClose={() => setSheet(null)}
      />
      <DeliveredSheet
        key={`delivered-${order.version}`}
        order={order}
        open={sheet === 'delivered'}
        busy={action.isPending}
        error={sheetError}
        onClose={() => setSheet(null)}
        onSubmit={(body: DeliveredBody) => run('delivered', body)}
      />
      {order.status === 'return_pending' && (
        <ReviewSheet
          key={`review-${order.version}`}
          order={order}
          open={sheet === 'review'}
          busy={action.isPending}
          error={sheetError}
          onClose={() => setSheet(null)}
          onSubmit={(body: ReviewBody) => run('returns/review', body)}
        />
      )}
      <Sheet
        open={sheet === 'cancel'}
        title={t('orders.cancelOrder')}
        onClose={() => setSheet(null)}
        busy={action.isPending}
        footer={
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="secondary" onClick={() => setSheet(null)} disabled={action.isPending}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="danger"
              loading={action.isPending}
              disabled={!reason.trim()}
              onClick={() => run('cancel', { reason: reason.trim() })}
            >
              {t('orders.cancelOrder')}
            </Button>
          </div>
        }
      >
        <p className="mb-3 text-sm text-stone-600">{t('orders.cancelBody', { code: order.code })}</p>
        <Field label={t('orders.cancelReason')}>
          {(id) => (
            <textarea
              id={id}
              rows={3}
              maxLength={ORDER_REASON_MAX_LENGTH}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="block w-full rounded-lg border-0 bg-white px-3 py-2 text-base text-stone-900 shadow-sm ring-1 ring-inset ring-stone-300 focus:ring-2 focus:ring-inset focus:ring-brand-500 sm:text-sm"
            />
          )}
        </Field>
        {sheetError && (
          <Alert tone="error" className="mt-3">
            {sheetError}
          </Alert>
        )}
      </Sheet>
    </>
  )
}
