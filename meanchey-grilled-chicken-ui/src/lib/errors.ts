import axios from 'axios'
import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import type { ApiErrorBody } from './types'
import { useFormatDate } from './format'

/** "07:44" in Cambodia time (attendance errors' instants). */
function clockTime(iso: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: 'Asia/Phnom_Penh',
  }).format(new Date(iso))
}

/** A client-side error with a translatable code, e.g. PASSWORDS_DO_NOT_MATCH. */
export class ClientError extends Error {
  constructor(
    public code: string,
    public details: Record<string, unknown> = {},
  ) {
    super(code)
  }
}

export function getError(err: unknown): { code: string; details: Record<string, unknown> } {
  if (err instanceof ClientError) return { code: err.code, details: err.details }
  if (axios.isAxiosError<ApiErrorBody>(err)) {
    if (!err.response) return { code: 'NETWORK_ERROR', details: {} }
    const body = err.response.data?.error
    if (body?.code) return { code: body.code, details: body.details ?? {} }
    return { code: 'HTTP_ERROR', details: {} }
  }
  return { code: 'UNKNOWN', details: {} }
}

/** Translate any error (API error code, network error, client error) into the UI language. */
interface InventoryShort {
  item_code: string
  name_en: string
  name_km: string
  available_count: number | null
  available_kg: string | null
  available_g?: string | null
  available_m2?: string | null
  needed_count: number | null
  needed_kg: string | null
  needed_g?: string | null
  needed_m2?: string | null
}

/** The unit that is short (count first), e.g. "Chicken: 0 available, 50 needed". */
function shortLine(t: TFunction, item: InventoryShort, lang: 'km' | 'en'): string {
  const name = (lang === 'km' ? item.name_km : item.name_en) || item.name_en
  const countShort =
    item.needed_count !== null && (item.available_count ?? 0) < item.needed_count
  // Materials measured in grams (e.g. Marinade sauce at step 2).
  const gramsShort = item.needed_g !== null && item.needed_g !== undefined
  const areaShort = item.needed_m2 !== null && item.needed_m2 !== undefined
  const [available, needed] = countShort
    ? [String(item.available_count ?? 0), String(item.needed_count)]
    : areaShort
      ? [
          t('inventory.m2Value', { value: Number(item.available_m2 ?? 0).toFixed(2) }),
          t('inventory.m2Value', { value: Number(item.needed_m2 ?? 0).toFixed(2) }),
        ]
      : gramsShort
      ? [
          t('inventory.gValue', { value: Number(item.available_g ?? 0).toFixed(1) }),
          t('inventory.gValue', { value: Number(item.needed_g ?? 0).toFixed(1) }),
        ]
      : [
          t('inventory.kgValue', { value: Number(item.available_kg ?? 0) }),
          t('inventory.kgValue', { value: Number(item.needed_kg ?? 0) }),
        ]
  return t('errors.inventoryShortItem', { name, available, needed })
}

export function useErrorMessage() {
  const { t, i18n } = useTranslation()
  const lang = i18n.language === 'en' ? 'en' : 'km'
  const formatDate = useFormatDate()
  return useCallback(
    (err: unknown): string => {
      const { code: apiCode, details } = getError(err)
      // A validation error may carry a more specific code (ATTENDANCE_START_IN_PAST).
      const code =
        apiCode === 'VALIDATION_ERROR' && typeof details.code === 'string' ? details.code : apiCode
      const params: Record<string, unknown> = { ...details }
      if (typeof details.locked_until === 'string') {
        params.time = formatDate(details.locked_until, { timeStyle: 'short' })
      }
      if (typeof details.min_length === 'number') params.min = details.min_length
      // ROLE_LIMIT_REACHED: {role, limit, active} → "The supervisor limit (3) is reached."
      if (typeof details.role === 'string') params.roleName = t(`userLimits.singular.${details.role}`)
      // INVENTORY_INSUFFICIENT: one sentence per item short ("Not enough Chicken in stock: …").
      if (code === 'INVENTORY_INSUFFICIENT' && Array.isArray(details.items)) {
        params.items = (details.items as InventoryShort[]).map((item) => shortLine(t, item, lang)).join(' ')
      }
      // PRODUCTION_STOCK_ALREADY_USED: {items, orders} → the order codes and the items.
      if (code === 'PRODUCTION_STOCK_ALREADY_USED') {
        const orders = Array.isArray(details.orders) ? (details.orders as string[]) : []
        params.orders = orders.join(', ') || '—'
        const items = Array.isArray(details.items) ? (details.items as { name_en: string; name_km: string }[]) : []
        params.items = items.map((i) => (lang === 'km' ? i.name_km : i.name_en) || i.name_en).join(', ')
      }
      // Attendance: times in the business time zone, shift names translated.
      for (const key of ['opens_at', 'next_opens_at', 'closed_at'] as const) {
        if (typeof details[key] === 'string') params[key] = clockTime(details[key] as string)
      }
      params.time = params.opens_at ?? params.next_opens_at ?? params.time
      for (const key of ['shift_code', 'next_shift_code'] as const) {
        if (typeof details[key] === 'string') {
          params[key === 'shift_code' ? 'shift' : 'nextShift'] = t(`attendance.shifts.${details[key]}`)
        }
      }
      // ATTENDANCE_NOT_STARTED: {start_date} → "20 Oct 2026".
      if (typeof details.start_date === 'string') {
        params.start_date = formatDate(`${details.start_date}T00:00:00Z`, { dateStyle: 'medium', timeZone: 'UTC' })
      }
      // ATTENDANCE_DAY_OFF: {reason, holidays} → "Pchum Ben" / "a day off".
      if (code === 'ATTENDANCE_DAY_OFF') {
        const holidays = Array.isArray(details.holidays) ? (details.holidays as { name_km: string; name_en: string }[]) : []
        params.what = holidays.length
          ? t('attendance.dayOff.holiday', {
              name: holidays.map((h) => (lang === 'km' ? h.name_km : h.name_en) || h.name_en).join(', '),
            })
          : t('attendance.dayOff.weekday')
      }
      params.min ??= 8
      return t(`errors.${code}`, { ...params, defaultValue: t('errors.UNKNOWN') })
    },
    [t, formatDate, lang],
  )
}
