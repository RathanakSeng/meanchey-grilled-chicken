/**
 * Decimal-safe numbers for production forms. Weights are handled as scaled integers
 * (kg × 1000, g × 10), never as floats, so sums and balances compare exactly — the same
 * precision the API stores (NUMERIC(10,3) / NUMERIC(10,1)).
 */

export const KG_PLACES = 3
export const GRAMS_PLACES = 1
/** Same bounds as the API. */
const MAX_DIGITS = 10
export const MAX_COUNT = 1_000_000

/** A value typed into a field: empty, valid (scaled), or not a valid number. */
export type Parsed = { kind: 'empty' } | { kind: 'ok'; value: number } | { kind: 'invalid' }

const EMPTY: Parsed = { kind: 'empty' }
const INVALID: Parsed = { kind: 'invalid' }

/** "12,5" and "12.5" both work (some keyboards only offer a comma). */
function clean(input: string): string {
  return input.trim().replace(',', '.')
}

/** Parse a non-negative decimal with at most `places` decimals into a scaled integer. */
export function parseDecimal(input: string, places: number): Parsed {
  const s = clean(input)
  if (s === '') return EMPTY
  const m = /^(\d*)(?:\.(\d*))?$/.exec(s)
  if (!m || (m[1] === '' && !m[2])) return INVALID
  const [, whole, fraction = ''] = m
  if (fraction.length > places) return INVALID
  const digits = (whole.replace(/^0+(?=\d)/, '') || '0') + fraction.padEnd(places, '0')
  if (digits.replace(/^0+/, '').length > MAX_DIGITS) return INVALID
  return { kind: 'ok', value: Number(digits) }
}

/** Parse a whole number ≥ 0. */
export function parseCount(input: string): Parsed {
  const s = input.trim()
  if (s === '') return EMPTY
  if (!/^\d+$/.test(s)) return INVALID
  const value = Number(s)
  return value > MAX_COUNT ? INVALID : { kind: 'ok', value }
}

/** Scaled integer → canonical API string ("12.500"). */
export function formatScaled(value: number, places: number): string {
  const sign = value < 0 ? '-' : ''
  const abs = Math.abs(value)
  if (places === 0) return `${sign}${abs}`
  const factor = 10 ** places
  const whole = Math.floor(abs / factor)
  const fraction = String(abs % factor).padStart(places, '0')
  return `${sign}${whole}.${fraction}`
}

/** API string ("12.500") → a friendly input value ("12.5"); null → "". */
export function toInput(value: string | null | undefined): string {
  if (value === null || value === undefined) return ''
  if (!value.includes('.')) return value
  return value.replace(/0+$/, '').replace(/\.$/, '')
}

export function countToInput(value: number | null | undefined): string {
  return value === null || value === undefined ? '' : String(value)
}

/** For draft saves: the API value of a field, `null` when empty, `undefined` (omit) when invalid. */
export function decimalPayload(input: string, places: number): string | null | undefined {
  const p = parseDecimal(input, places)
  if (p.kind === 'empty') return null
  if (p.kind === 'invalid') return undefined
  return formatScaled(p.value, places)
}

export function countPayload(input: string): number | null | undefined {
  const p = parseCount(input)
  if (p.kind === 'empty') return null
  if (p.kind === 'invalid') return undefined
  return p.value
}

/** Scaled value of an API string (or null). */
export function scaledOf(value: string | null | undefined, places: number): number | null {
  if (value === null || value === undefined) return null
  const p = parseDecimal(value, places)
  return p.kind === 'ok' ? p.value : null
}

export function valueOf(p: Parsed): number | null {
  return p.kind === 'ok' ? p.value : null
}

/** Drop keys whose value is `undefined` (invalid inputs aren't sent; the server keeps its value). */
export function compact<T extends Record<string, unknown>>(obj: T): Partial<T> {
  return Object.fromEntries(Object.entries(obj).filter(([, v]) => v !== undefined)) as Partial<T>
}
