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
