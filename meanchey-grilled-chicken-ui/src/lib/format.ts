import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import type { Localized } from './types'

export function useFormatDate() {
  const { i18n } = useTranslation()
  const locale = i18n.language === 'km' ? 'km-KH' : 'en-GB'
  return useCallback(
    (
      iso: string | null | undefined,
      options: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'short' },
    ) => (iso ? new Intl.DateTimeFormat(locale, options).format(new Date(iso)) : '—'),
    [locale],
  )
}

/**
 * A calendar date from the API ("2026-09-29", e.g. a production step date), shown as that same
 * day whatever the device's time zone.
 */
export function useFormatDay() {
  const formatDate = useFormatDate()
  return useCallback(
    (day: string | null | undefined, options: Intl.DateTimeFormatOptions = { dateStyle: 'medium' }) =>
      formatDate(day, { ...options, timeZone: 'UTC' }),
    [formatDate],
  )
}

/**
 * "2 h ago" / "២ ម៉ោងមុន" for a past ISO time, from our own translations (`common.relative.*`):
 * browsers often lack Khmer data for `Intl.RelativeTimeFormat`. Older than a week: the date.
 */
export function useRelativeTime() {
  const { t } = useTranslation()
  const formatDate = useFormatDate()
  return useCallback(
    (iso: string, now: number = Date.now()): string => {
      const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
      if (seconds < 60) return t('common.relative.justNow')
      if (seconds < 3600) return t('common.relative.minutesAgo', { count: Math.round(seconds / 60) })
      if (seconds < 86400) return t('common.relative.hoursAgo', { count: Math.round(seconds / 3600) })
      if (seconds < 7 * 86400) return t('common.relative.daysAgo', { count: Math.round(seconds / 86400) })
      return formatDate(iso, { dateStyle: 'medium' })
    },
    [t, formatDate],
  )
}

/** Pick `name_km` / `name_en` (or any `<field>_km` / `<field>_en`) for the current language. */
export function useLocalized() {
  const { i18n } = useTranslation()
  const lang = i18n.language === 'en' ? 'en' : 'km'
  return useCallback(
    <T extends Localized>(obj: T, field: 'name' | 'description' = 'name'): string => {
      const record = obj as unknown as Record<string, string>
      return record[`${field}_${lang}`] || record[`${field}_en`] || ''
    },
    [lang],
  )
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  return (parts[0]?.[0] ?? '?').toUpperCase() + (parts[1]?.[0] ?? '').toUpperCase()
}

/** Same normalization as the API: strip a leading '@', lowercase. */
export function normalizeUsername(value: string): string {
  return value.trim().replace(/^@/, '').toLowerCase()
}
