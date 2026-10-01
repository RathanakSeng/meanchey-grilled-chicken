import axios from 'axios'
import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import type { ApiErrorBody } from './types'
import { useFormatDate } from './format'

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
  needed_count: number | null
  needed_kg: string | null
}

/** The unit that is short (count first), e.g. "Chicken: 0 available, 50 needed". */
function shortLine(t: TFunction, item: InventoryShort, lang: 'km' | 'en'): string {
  const name = (lang === 'km' ? item.name_km : item.name_en) || item.name_en
  const countShort =
    item.needed_count !== null && (item.available_count ?? 0) < item.needed_count
  const [available, needed] = countShort
    ? [String(item.available_count ?? 0), String(item.needed_count)]
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
      const { code, details } = getError(err)
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
      params.min ??= 8
      return t(`errors.${code}`, { ...params, defaultValue: t('errors.UNKNOWN') })
    },
    [t, formatDate, lang],
  )
}
