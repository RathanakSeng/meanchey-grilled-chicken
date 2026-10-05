import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * Inventory quantity units, one rule everywhere (mirror of the API's app/inventory/units.py):
 * count = whole number, kg = 3 decimals, g = 1 decimal. Amounts are handled as scaled integers
 * (kg × 1000, g × 10) so sums and previews are exact; the API exchanges them as strings
 * ("1.250", "350.0") or, for counts, numbers.
 */
export type QuantityUnit = 'count' | 'kg' | 'g'
export const QUANTITY_UNITS: QuantityUnit[] = ['kg', 'g', 'count']
export const UNIT_DECIMALS: Record<QuantityUnit, number> = { count: 0, kg: 3, g: 1 }
/** Largest amount for one add / remove (same as the API). */
const MAX_SCALED: Record<QuantityUnit, number> = { count: 10_000_000, kg: 999_999_999, g: 999_999_999 }

export type ParsedQuantity = { kind: 'empty' } | { kind: 'ok'; scaled: number } | { kind: 'invalid' }

/** "1,5" and "1.5" both work (some keyboards only offer a comma). Must be > 0. */
export function parseQuantity(input: string, unit: QuantityUnit): ParsedQuantity {
  const s = input.trim().replace(',', '.')
  if (s === '') return { kind: 'empty' }
  const places = UNIT_DECIMALS[unit]
  const m = /^(\d*)(?:\.(\d*))?$/.exec(s)
  if (!m || (m[1] === '' && !m[2])) return { kind: 'invalid' }
  const [, whole, fraction = ''] = m
  if (fraction.replace(/0+$/, '').length > places) return { kind: 'invalid' }
  const digits = (whole || '0') + fraction.padEnd(places, '0').slice(0, places)
  const scaled = Number(digits)
  if (!Number.isFinite(scaled) || scaled <= 0 || scaled > MAX_SCALED[unit]) return { kind: 'invalid' }
  return { kind: 'ok', scaled }
}

/** An API amount ("1.250", "350.0", 12) as a scaled integer. */
export function scaledOfAmount(value: string | number | null | undefined, unit: QuantityUnit): number {
  if (value === null || value === undefined) return 0
  return Math.round(Number(value) * 10 ** UNIT_DECIMALS[unit])
}

/** Scaled integer → the API string ("1.250") or number (counts). */
export function toApiQuantity(scaled: number, unit: QuantityUnit): string | number {
  const places = UNIT_DECIMALS[unit]
  if (places === 0) return scaled
  const factor = 10 ** places
  const sign = scaled < 0 ? '-' : ''
  const abs = Math.abs(scaled)
  return `${sign}${Math.floor(abs / factor)}.${String(abs % factor).padStart(places, '0')}`
}

/** The balance of an item / material in `unit` (its count, kg or g field). */
export function amountIn(
  item: { count: number | null; kg: string | null; g?: string | null },
  unit: QuantityUnit,
): string | number | null {
  return unit === 'count' ? item.count : unit === 'kg' ? item.kg : (item.g ?? null)
}

/**
 * Display: "12", "1.250 kg", "2,350.0 g" — always the unit's decimals, thousands separators in
 * the UI language. `signed` adds "+" to positive values (movements).
 */
export function useQuantityFormat() {
  const { t, i18n } = useTranslation()
  const locale = i18n.language === 'km' ? 'km-KH' : 'en-GB'
  return useCallback(
    (value: string | number, unit: QuantityUnit, signed = false) => {
      const places = UNIT_DECIMALS[unit]
      const text = new Intl.NumberFormat(locale, {
        minimumFractionDigits: places,
        maximumFractionDigits: places,
        signDisplay: signed ? 'exceptZero' : 'auto',
      }).format(Number(value))
      return unit === 'count' ? text : t(unit === 'kg' ? 'inventory.kgValue' : 'inventory.gValue', { value: text })
    },
    [locale, t],
  )
}
