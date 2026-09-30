import axios from 'axios'
import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
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
export function useErrorMessage() {
  const { t } = useTranslation()
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
      params.min ??= 8
      return t(`errors.${code}`, { ...params, defaultValue: t('errors.UNKNOWN') })
    },
    [t, formatDate],
  )
}
