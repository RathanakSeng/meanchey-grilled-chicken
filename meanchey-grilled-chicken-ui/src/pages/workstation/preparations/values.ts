/**
 * Preparation form values (strings, as typed), the draft payload and the Finish rules — pure
 * functions, like production's steps.ts. Numbers are parsed into scaled integers (never floats):
 * satay sauce in grams (1 decimal), zip bags and packaging quantities in their material's unit
 * (count whole, kg 3 decimals, g 1 decimal), sachets whole.
 */
import { UNIT_DECIMALS, type QuantityUnit } from '@/lib/quantity'
import type { PackSize, Preparation, PreparationMaterial } from '@/lib/types'
import { formatScaled, parseCount, parseDecimal, toInput } from '@/pages/workstation/production/numbers'
import type { FieldError } from '@/pages/workstation/production/steps'

export const PACK_SIZES: PackSize[] = [2, 4]

export interface SatayLineValues {
  include: boolean
  satay_g: string
  zip_bag_qty: string
  sachets: string
}

export interface PackagingLineValues {
  material_id: string
  quantity: string
}

export interface PreparationValues {
  satay: Record<PackSize, SatayLineValues>
  packaging: PackagingLineValues[]
  note: string
}

const emptySatay = (): SatayLineValues => ({ include: false, satay_g: '', zip_bag_qty: '', sachets: '' })

export function fromPreparation(p: Preparation): PreparationValues {
  const satay: Record<PackSize, SatayLineValues> = { 2: emptySatay(), 4: emptySatay() }
  const packaging: PackagingLineValues[] = []
  for (const line of p.lines) {
    if (line.pack_size) {
      satay[line.pack_size] = {
        include: true,
        satay_g: toInput(line.satay_g),
        zip_bag_qty: toInput(line.zip_bag_qty),
        sachets: line.sachets === null ? '' : String(line.sachets),
      }
    } else if (line.material) {
      packaging.push({ material_id: line.material.id, quantity: toInput(line.quantity) })
    }
  }
  return { satay, packaging, note: p.note ?? '' }
}

/** A typed amount in `unit` (≥ 0) as scaled integer, or empty / invalid. */
export function parseAmount(input: string, unit: QuantityUnit) {
  return unit === 'count' ? parseCount(input) : parseDecimal(input, UNIT_DECIMALS[unit])
}

function apiAmount(input: string, unit: QuantityUnit): string | number | undefined {
  const parsed = parseAmount(input, unit)
  if (parsed.kind !== 'ok') return undefined
  return unit === 'count' ? parsed.value : formatScaled(parsed.value, UNIT_DECIMALS[unit])
}

/** Units the form needs: the zip bags' per pack size, each packaging material's. */
export interface UnitContext {
  zipUnit(size: PackSize): QuantityUnit
  materialUnit(id: string): QuantityUnit
}

/** The draft body (without `version`). Invalid inputs are left out of the line. */
export function toPayload(
  type: Preparation['type'],
  v: PreparationValues,
  units: UnitContext,
): Record<string, unknown> {
  const lines =
    type === 'satay_sachet'
      ? PACK_SIZES.filter((size) => v.satay[size].include).map((size) => {
          const l = v.satay[size]
          return {
            pack_size: size,
            satay_g: apiAmount(l.satay_g, 'g'),
            zip_bag_qty: apiAmount(l.zip_bag_qty, units.zipUnit(size)),
            sachets: apiAmount(l.sachets, 'count'),
          }
        })
      : v.packaging.map((l) => ({
          material_id: l.material_id,
          quantity: apiAmount(l.quantity, units.materialUnit(l.material_id)),
        }))
  // JSON drops undefined: a missing value is simply not sent.
  return JSON.parse(JSON.stringify({ lines, note: v.note.trim() || null }))
}

export type Errors = Record<string, FieldError>

const UNIT_ERROR: Record<QuantityUnit, FieldError> = {
  count: 'invalidCount',
  kg: 'invalidKg',
  g: 'invalidG',
  m2: 'invalidM2',
}

function check(errors: Errors, key: string, input: string, unit: QuantityUnit, finish: boolean) {
  const parsed = parseAmount(input, unit)
  if (parsed.kind === 'invalid') errors[key] = UNIT_ERROR[unit]
  else if (finish && parsed.kind === 'empty') errors[key] = 'required'
  else if (finish && parsed.kind === 'ok' && parsed.value <= 0) errors[key] = 'positive'
}

/** Field errors while typing (`finish = false`: only invalid numbers) or for Finish. */
export function fieldErrors(
  type: Preparation['type'],
  v: PreparationValues,
  units: UnitContext,
  finish: boolean,
): Errors {
  const errors: Errors = {}
  if (type === 'satay_sachet') {
    for (const size of PACK_SIZES) {
      const l = v.satay[size]
      if (!l.include) continue
      check(errors, `${size}.satay_g`, l.satay_g, 'g', finish)
      check(errors, `${size}.zip_bag_qty`, l.zip_bag_qty, units.zipUnit(size), finish)
      check(errors, `${size}.sachets`, l.sachets, 'count', finish)
    }
  } else {
    for (const l of v.packaging) {
      check(errors, `${l.material_id}.quantity`, l.quantity, units.materialUnit(l.material_id), finish)
    }
  }
  return errors
}

/** A material's stock as a scaled integer in its own unit. */
export function stockScaled(m: PreparationMaterial): number {
  const parsed = parseDecimal(m.stock, UNIT_DECIMALS[m.unit])
  return parsed.kind === 'ok' ? parsed.value : 0
}

/** Scaled grams (× 10) of satay sauce in the material's unit, scaled (kg × 1000 or g × 10). */
export function gramsInUnit(scaledGrams: number, unit: QuantityUnit): number {
  // g × 10 → kg × 1000 (= whole grams) is ÷ 10, rounded half up like the API.
  return unit === 'kg' ? Math.round(scaledGrams / 10) : scaledGrams
}

export function lineCount(type: Preparation['type'], v: PreparationValues): number {
  return type === 'satay_sachet' ? PACK_SIZES.filter((s) => v.satay[s].include).length : v.packaging.length
}
