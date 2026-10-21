import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useIsMobileLayout } from '@/layouts/useIsMobileLayout'
import { api } from '@/lib/api'
import { useCalendarNames, useFormatDate } from '@/lib/format'
import { paths } from '@/lib/paths'
import { useDuration } from '@/pages/attendance/api'
import { boxCountsText } from '@/pages/workstation/orders/badges'
import {
  BOX_COLORS,
  type AppNotification,
  type NotificationPage,
  type OrderAlertItem,
  type PreparationAlertMaterial,
} from '@/lib/types'
import { Icon } from './icons'
import { Sheet } from './Sheet'
import { Button, Spinner, cx } from './ui'

/** Query keys (see docs/ARCHITECTURE.md). */
export const notificationKeys = {
  all: ['notifications'] as const,
  list: (params: object) => ['notifications', params] as const,
  unread: ['notifications-unread'] as const,
}

const LIST_PARAMS = { page_size: 20 }

const ORDER_EMOJI: Partial<Record<AppNotification['type'], string>> = {
  'order.delivering': '🚚',
  'order.delivered': '✅',
  'order.return_pending': '↩️',
  'order.returns_reviewed': '📦',
}

function isOrderAlert(n: AppNotification): boolean {
  return n.type.startsWith('order.')
}

function isRequestAlert(n: AppNotification): boolean {
  return n.type.startsWith('attendance.request_')
}

const REQUEST_EMOJI: Partial<Record<AppNotification['type'], string>> = {
  'attendance.request_submitted': '📝',
  'attendance.request_approved': '✅',
  'attendance.request_rejected': '❌',
  'attendance.request_reminder': '🔔',
}

/** ✅ processing finished · 🎉 completed as planned · ⚠️ completed, different from the plan;
 * orders: 🚚 out for delivery · ✅ delivered · ↩️ returned · 📦 return reviewed. */
function emoji(n: AppNotification): string {
  if (isOrderAlert(n)) return ORDER_EMOJI[n.type] ?? '🧾'
  if (isRequestAlert(n)) return REQUEST_EMOJI[n.type] ?? '📝'
  if (n.type === 'preparation.finished') return '🧂'
  if (n.type === 'production.processing_finished') return '✅'
  return n.payload.matches ? '🎉' : '⚠️'
}

/** The alert text, built from `type` + `payload` in the UI language. */
export function useNotificationText() {
  const { t, i18n } = useTranslation()
  const duration = useDuration()
  const names = useCalendarNames()
  return (n: AppNotification): { text: string; comment: string | null } => {
    const p = n.payload
    const again = p.repeat ? t('notifications.again') : ''
    if (isRequestAlert(n)) {
      const month = `${names.month(Number(p.month))} ${p.year}`
      const cut = Number(p.salary_cut_minutes ?? 0)
      const work = Number(p.unpaid_work_minutes ?? 0)
      const split = [
        cut > 0 && t('attendance.requests.splitCut', { duration: duration(cut) }),
        work > 0 && t('attendance.requests.splitWork', { duration: duration(work) }),
      ]
        .filter(Boolean)
        .join(', ')
      const missing = duration(Number(p.missing_minutes ?? 0))
      if (n.type === 'attendance.request_submitted') {
        return { text: t('notifications.requestSubmitted', { name: p.name, month, missing, split }), comment: null }
      }
      if (n.type === 'attendance.request_approved') {
        return {
          text: t(p.with_changes ? 'notifications.requestApprovedChanges' : 'notifications.requestApproved', { month, split }),
          comment: typeof p.comment === 'string' ? p.comment : null,
        }
      }
      if (n.type === 'attendance.request_rejected') {
        return { text: t('notifications.requestRejected', { month, reason: p.reason }), comment: null }
      }
      return {
        text: t('notifications.requestReminder', {
          month,
          missing,
          deadline: `${p.deadline_day} ${names.month(Number(p.deadline_month))}`,
        }),
        comment: null,
      }
    }
    if (isOrderAlert(n)) {
      // "3 × 4-Piece Packs, 0.250 kg Liver (packed)" in the UI language.
      const items = (value: unknown) => {
        const list = Array.isArray(value) ? (value as OrderAlertItem[]) : []
        if (list.length === 0) return t('notifications.orderNothing')
        return list
          .map((i) => {
            const name = (i18n.language === 'en' ? i.name_en : i.name_km) || i.name_en
            return i.count !== null
              ? t('notifications.orderItemCount', { name, count: i.count })
              : t('notifications.orderItemKg', { name, kg: i.kg })
          })
          .join(', ')
      }
      // A direct order has no customer name: "Direct order · 012 345 678".
      const customer = p.customer ?? t('orders.directOrderWithPhone', { phone: p.customer_phone ?? '—' })
      const common = { code: p.code, customer }
      if (n.type === 'order.delivering') {
        // "2 white boxes, 1 plastic bag" (alerts from before the bags only carry white / black).
        const counts = Object.fromEntries(BOX_COLORS.map((c) => [c, Number(p[c] ?? 0)]))
        const boxes = boxCountsText(t, counts) || t('notifications.orderNothing')
        return { text: t('notifications.orderDelivering', { ...common, boxes }), comment: null }
      }
      if (n.type === 'order.delivered') return { text: t('notifications.orderDelivered', common), comment: null }
      if (n.type === 'order.return_pending') {
        return {
          text: t('notifications.orderReturnPending', { ...common, summary: items(p.returned) }),
          comment: typeof p.reason === 'string' ? p.reason : null,
        }
      }
      return {
        text: t('notifications.orderReturnsReviewed', {
          code: p.code,
          outcome: t(p.outcome === 'fully_returned' ? 'orders.status.fully_returned' : 'orders.status.partly_returned'),
          toStock: items(p.to_stock),
          toWasted: items(p.to_wasted),
        }),
        comment: null,
      }
    }
    if (n.type === 'preparation.finished') {
      // "40 satay sachets (2-piece), 25 (4-piece) | Skewer 2.000 kg, String 0.500 kg".
      const sachets = ([2, 4] as const)
        .filter((size) => p[`sachets_${size}`])
        .map((size, i) =>
          t(i === 0 ? 'notifications.prepSachetsFirst' : 'notifications.prepSachetsMore', {
            n: Number(p[`sachets_${size}`]),
            size,
          }),
        )
      const materials = (Array.isArray(p.materials) ? (p.materials as PreparationAlertMaterial[]) : []).map((m) => {
        const name = (i18n.language === 'en' ? m.name_en : m.name_km) || m.name_en
        return m.unit === 'count' ? `${name} ${m.quantity}` : `${name} ${t(`notifications.prepUnit_${m.unit}`, { value: m.quantity })}`
      })
      const groups = [sachets.join(', '), materials.join(', ')].filter(Boolean)
      return {
        text: t('notifications.preparationFinished', {
          code: p.code,
          again,
          summary: groups.length ? groups.join(' | ') : t('notifications.orderNothing'),
        }),
        comment: null,
      }
    }
    if (n.type === 'production.processing_finished') {
      return {
        text: t('notifications.processingFinished', {
          code: p.code,
          again,
          quantity: p.quantity,
          wings: p.wings,
          thighs: p.thighs,
        }),
        comment: null,
      }
    }
    if (p.matches) {
      return {
        text: t('notifications.completedAsPlanned', { code: p.code, again, big: p.actual_big, small: p.actual_small }),
        comment: null,
      }
    }
    return {
      text: t('notifications.completedDiffers', {
        code: p.code,
        again,
        pb: p.planned_big ?? '—',
        ps: p.planned_small ?? '—',
        ab: p.actual_big ?? '—',
        as: p.actual_small ?? '—',
      }),
      comment: typeof p.comment === 'string' ? p.comment : null,
    }
  }
}

function targetOf(n: AppNotification): string {
  if (n.type === 'attendance.request_reminder') return paths.attendanceRequests
  if (isRequestAlert(n)) return `${paths.attendanceRequests}?request=${n.entity_id}`
  if (isOrderAlert(n)) return paths.order(n.entity_id)
  if (n.type === 'preparation.finished') return paths.preparation(n.entity_id)
  return n.type === 'production.processing_finished'
    ? paths.productionPlan(n.entity_id)
    : paths.productionBatch(n.entity_id, 3)
}

function Items({ onDone }: { onDone(): void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const formatDate = useFormatDate()
  const textOf = useNotificationText()

  const list = useQuery({
    queryKey: notificationKeys.list(LIST_PARAMS),
    queryFn: async () => (await api.get<NotificationPage>('/notifications', { params: LIST_PARAMS })).data,
  })
  const refresh = () => void queryClient.invalidateQueries({ queryKey: notificationKeys.all })
  const unread = () => void queryClient.invalidateQueries({ queryKey: notificationKeys.unread })
  const read = useMutation({
    mutationFn: (id: string) => api.post(`/notifications/${id}/read`),
    onSettled: () => {
      refresh()
      unread()
    },
  })
  const readAll = useMutation({
    mutationFn: () => api.post('/notifications/read-all'),
    onSettled: () => {
      refresh()
      unread()
    },
  })

  const open = (n: AppNotification) => {
    if (!n.read_at) read.mutate(n.id)
    onDone()
    navigate(targetOf(n))
  }

  if (list.isPending) {
    return (
      <div className="flex justify-center py-8 text-brand-600">
        <Spinner />
      </div>
    )
  }
  const items = list.data?.items ?? []
  return (
    <div>
      {items.length === 0 ? (
        <p className="px-4 py-10 text-center text-sm text-stone-500">{t('notifications.empty')}</p>
      ) : (
        <ul className="divide-y divide-stone-100">
          {items.map((n) => {
            const { text, comment } = textOf(n)
            return (
              <li key={n.id}>
                <button
                  type="button"
                  onClick={() => open(n)}
                  className={cx(
                    'flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-stone-50',
                    !n.read_at && 'bg-brand-50/50',
                  )}
                >
                  <span aria-hidden className="mt-0.5 text-lg leading-none">
                    {emoji(n)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={cx('block text-sm text-stone-800', !n.read_at && 'font-medium')}>{text}</span>
                    {comment && <span className="mt-0.5 block text-sm italic text-stone-600">“{comment}”</span>}
                    <span className="mt-0.5 block text-xs text-stone-500">{formatDate(n.created_at)}</span>
                    {(n.telegram_status === 'not_linked' || n.telegram_status === 'failed') && (
                      <span className="mt-0.5 block text-xs text-amber-700">
                        {t(n.telegram_status === 'not_linked' ? 'telegramLink.notSentNotLinked' : 'telegramLink.notSent')}
                      </span>
                    )}
                  </span>
                  {!n.read_at && (
                    <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand-600" aria-label={t('notifications.unread')} />
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {items.some((n) => !n.read_at) && (
        <div className="border-t border-stone-100 p-2">
          <Button variant="ghost" block loading={readAll.isPending} onClick={() => readAll.mutate()}>
            <Icon name="check" width={16} height={16} />
            {t('notifications.markAllRead')}
          </Button>
        </div>
      )}
    </div>
  )
}

/**
 * The header bell (desktop and mobile top bars): unread count polled every 60 s and on window
 * focus, from the app shell rather than per page. A dropdown on desktop, a sheet on mobile.
 */
export function NotificationBell() {
  const { t } = useTranslation()
  const isMobile = useIsMobileLayout()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const unread = useQuery({
    queryKey: notificationKeys.unread,
    queryFn: async () =>
      (await api.get<NotificationPage>('/notifications', { params: { unread_only: true, page_size: 1 } })).data
        .unread_count,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  })
  const count = unread.data ?? 0

  // Close the desktop dropdown on an outside click.
  useEffect(() => {
    if (!open || isMobile) return
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open, isMobile])

  const toggle = () => {
    if (!open) void queryClient.invalidateQueries({ queryKey: notificationKeys.all })
    setOpen((o) => !o)
  }

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={toggle}
        aria-label={count > 0 ? t('notifications.titleUnread', { count }) : t('notifications.title')}
        aria-haspopup="dialog"
        aria-expanded={open}
        className="relative inline-flex h-9 w-9 items-center justify-center rounded-full text-stone-600 hover:bg-stone-100"
      >
        <Icon name="bell" />
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 inline-flex min-w-[1.1rem] items-center justify-center rounded-full bg-brand-600 px-1 text-[10px] font-semibold leading-4 tabular-nums text-white ring-2 ring-white">
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>
      {isMobile ? (
        // Portal: the header's backdrop-blur would otherwise contain the fixed sheet.
        createPortal(
          <Sheet open={open} title={t('notifications.title')} onClose={() => setOpen(false)}>
            <div className="-mx-5 -my-4">{open && <Items onDone={() => setOpen(false)} />}</div>
          </Sheet>,
          document.body,
        )
      ) : (
        open && (
          <div
            role="dialog"
            aria-label={t('notifications.title')}
            className="absolute right-0 z-40 mt-2 w-96 overflow-hidden rounded-xl bg-white shadow-lg ring-1 ring-stone-200"
          >
            <p className="border-b border-stone-100 px-4 py-3 text-sm font-semibold text-stone-900">
              {t('notifications.title')}
            </p>
            <div className="max-h-[28rem] overflow-y-auto">
              <Items onDone={() => setOpen(false)} />
            </div>
          </div>
        )
      )}
    </div>
  )
}
