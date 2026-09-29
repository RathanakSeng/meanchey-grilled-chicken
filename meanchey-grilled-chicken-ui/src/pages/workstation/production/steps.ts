/**
 * Form values, draft payloads and client-side Finish rules of the three steps.
 *
 * The API enforces the same rules at Finish, except the by-product balance
 * (carried forward + rejected = produced kg), which is enforced here only (a documented UI rule
 * that may be relaxed later).
 */
import type { ProductionBatch, SupplierBrief, SupplierOption } from '@/lib/types'
import {
  GRAMS_PLACES,
  KG_PLACES,
  compact,
  countPayload,
  countToInput,
  decimalPayload,
  parseCount,
  parseDecimal,
  scaledOf,
  toInput,
  valueOf,
} from './numbers'

/** i18n key suffix under `production.errors.*`. */
export type FieldError = 'required' | 'positive' | 'invalidKg' | 'invalidG' | 'invalidCount'
export type Errors = Record<string, FieldError>

function kgError(input: string, { required = false, positive = false } = {}): FieldError | null {
  const p = parseDecimal(input, KG_PLACES)
  if (p.kind === 'invalid') return 'invalidKg'
  if (p.kind === 'empty') return required ? 'required' : null
  return positive && p.value <= 0 ? 'positive' : null
}

function gramsError(input: string, required: boolean): FieldError | null {
  const p = parseDecimal(input, GRAMS_PLACES)
  if (p.kind === 'invalid') return 'invalidG'
  return p.kind === 'empty' && required ? 'required' : null
}

function countError(input: string, { required = false, positive = false } = {}): FieldError | null {
  const p = parseCount(input)
  if (p.kind === 'invalid') return 'invalidCount'
  if (p.kind === 'empty') return required ? 'required' : null
  return positive && p.value <= 0 ? 'positive' : null
}

function collect(entries: [string, FieldError | null][]): Errors {
  return Object.fromEntries(entries.filter(([, e]) => e !== null)) as Errors
}

function byproductCodes(batch: ProductionBatch): string[] {
  return [...batch.catalog.byproducts].sort((a, b) => a.order - b.order).map((b) => b.code)
}

function byproductRow(batch: ProductionBatch, code: string) {
  return batch.byproducts.find((b) => b.item_code === code)
}

// --- Step 1: intake ------------------------------------------------------------------------------
// No date here: the import date is recorded by the server when the step is finished.

export interface RawValues {
  supplier: (SupplierOption & Partial<Pick<SupplierBrief, 'is_active'>>) | null
  material_kind: string
  weight_kg: string
  quantity: string
}

export function rawFromBatch(batch: ProductionBatch): RawValues {
  const raw = batch.raw_material
  return {
    supplier: raw.supplier,
    material_kind: raw.material_kind,
    weight_kg: toInput(raw.weight_kg),
    quantity: countToInput(raw.quantity),
  }
}

export function rawPayload(v: RawValues): Record<string, unknown> {
  return compact({
    supplier_id: v.supplier?.id ?? null,
    material_kind: v.material_kind,
    weight_kg: decimalPayload(v.weight_kg, KG_PLACES),
    quantity: countPayload(v.quantity),
  })
}

/** Format problems shown while typing. */
export function rawInputErrors(v: RawValues): Errors {
  return collect([
    ['weight_kg', kgError(v.weight_kg)],
    ['quantity', countError(v.quantity)],
  ])
}

export function rawFinishErrors(v: RawValues): Errors {
  return collect([
    ['supplier', v.supplier ? null : 'required'],
    ['weight_kg', kgError(v.weight_kg, { required: true, positive: true })],
    ['quantity', countError(v.quantity, { required: true, positive: true })],
  ])
}

// --- Step 2: processing --------------------------------------------------------------------------

export interface ProducedValues {
  wings_kg: string
  thighs_kg: string
  marinade_g: string
  byproducts: Record<string, string>
}

export function producedFromBatch(batch: ProductionBatch): ProducedValues {
  const p = batch.produced
  return {
    wings_kg: toInput(p?.wings_kg),
    thighs_kg: toInput(p?.thighs_kg),
    marinade_g: toInput(p?.marinade_g),
    byproducts: Object.fromEntries(
      byproductCodes(batch).map((code) => [code, toInput(byproductRow(batch, code)?.produced_kg)]),
    ),
  }
}

export function producedPayload(v: ProducedValues): Record<string, unknown> {
  return compact({
    wings_kg: decimalPayload(v.wings_kg, KG_PLACES),
    thighs_kg: decimalPayload(v.thighs_kg, KG_PLACES),
    marinade_g: decimalPayload(v.marinade_g, GRAMS_PLACES),
    byproducts: compact(
      Object.fromEntries(
        Object.entries(v.byproducts).map(([code, kg]) => [code, decimalPayload(kg, KG_PLACES)]),
      ),
    ),
  })
}

export function producedInputErrors(v: ProducedValues): Errors {
  return collect([
    ['wings_kg', kgError(v.wings_kg)],
    ['thighs_kg', kgError(v.thighs_kg)],
    ['marinade_g', gramsError(v.marinade_g, false)],
    ...Object.entries(v.byproducts).map(
      ([code, kg]) => [`byproducts.${code}`, kgError(kg)] as [string, FieldError | null],
    ),
  ])
}

export function producedFinishErrors(v: ProducedValues): Errors {
  return collect([
    ['wings_kg', kgError(v.wings_kg, { required: true, positive: true })],
    ['thighs_kg', kgError(v.thighs_kg, { required: true, positive: true })],
    ['marinade_g', gramsError(v.marinade_g, true)],
    ...Object.entries(v.byproducts).map(
      ([code, kg]) =>
        [`byproducts.${code}`, kgError(kg, { required: true })] as [string, FieldError | null],
    ),
  ])
}

// --- Step 3: standardize -------------------------------------------------------------------------

export interface StandardizeValues {
  big_packages: string
  small_packages: string
  rejected_wings: string
  rejected_thighs: string
  comment: string
  byproducts: Record<string, { carry_kg: string; rejected_kg: string }>
}

export const PIECES_PER_BIG = 2
export const PIECES_PER_SMALL = 1

export function standardizeFromBatch(batch: ProductionBatch): StandardizeValues {
  const s = batch.standardize
  return {
    big_packages: countToInput(s?.big_packages),
    small_packages: countToInput(s?.small_packages),
    rejected_wings: countToInput(s?.rejected_wings),
    rejected_thighs: countToInput(s?.rejected_thighs),
    comment: s?.comment ?? '',
    byproducts: Object.fromEntries(
      byproductCodes(batch).map((code) => {
        const row = byproductRow(batch, code)
        return [code, { carry_kg: toInput(row?.carry_kg), rejected_kg: toInput(row?.rejected_kg) }]
      }),
    ),
  }
}

export function standardizePayload(v: StandardizeValues): Record<string, unknown> {
  return compact({
    big_packages: countPayload(v.big_packages),
    small_packages: countPayload(v.small_packages),
    rejected_wings: countPayload(v.rejected_wings),
    rejected_thighs: countPayload(v.rejected_thighs),
    comment: v.comment.trim() || null,
    byproducts: Object.fromEntries(
      Object.entries(v.byproducts).map(([code, row]) => [
        code,
        compact({
          carry_kg: decimalPayload(row.carry_kg, KG_PLACES),
          rejected_kg: decimalPayload(row.rejected_kg, KG_PLACES),
        }),
      ]),
    ),
  })
}

export function standardizeInputErrors(v: StandardizeValues): Errors {
  return collect([
    ['big_packages', countError(v.big_packages)],
    ['small_packages', countError(v.small_packages)],
    ['rejected_wings', countError(v.rejected_wings)],
    ['rejected_thighs', countError(v.rejected_thighs)],
    ...Object.entries(v.byproducts).flatMap(([code, row]) => [
      [`byproducts.${code}.carry_kg`, kgError(row.carry_kg)] as [string, FieldError | null],
      [`byproducts.${code}.rejected_kg`, kgError(row.rejected_kg)] as [string, FieldError | null],
    ]),
  ])
}

export function standardizeFinishErrors(v: StandardizeValues): Errors {
  const required = { required: true }
  return collect([
    ['big_packages', countError(v.big_packages, required)],
    ['small_packages', countError(v.small_packages, required)],
    ['rejected_wings', countError(v.rejected_wings, required)],
    ['rejected_thighs', countError(v.rejected_thighs, required)],
    ...Object.entries(v.byproducts).flatMap(([code, row]) => [
      [`byproducts.${code}.carry_kg`, kgError(row.carry_kg, required)] as [string, FieldError | null],
      [`byproducts.${code}.rejected_kg`, kgError(row.rejected_kg, required)] as [
        string,
        FieldError | null,
      ],
    ]),
  ])
}

export interface PieceBalance {
  expected: number
  assigned: number
  /** > 0: still to assign; < 0: too many. */
  left: number
}

/** Wings and thighs: 2 per big package, 1 per small one, plus rejected. Empty counts as 0. */
export function pieceBalance(
  batch: ProductionBatch,
  v: StandardizeValues,
): { wings: PieceBalance; thighs: PieceBalance; packedPerType: number } {
  const n = (s: string) => valueOf(parseCount(s)) ?? 0
  const packed = PIECES_PER_BIG * n(v.big_packages) + PIECES_PER_SMALL * n(v.small_packages)
  const make = (expected: number, rejected: string): PieceBalance => {
    const assigned = packed + n(rejected)
    return { expected, assigned, left: expected - assigned }
  }
  return {
    wings: make(batch.produced?.wings_count ?? 0, v.rejected_wings),
    thighs: make(batch.produced?.thighs_count ?? 0, v.rejected_thighs),
    packedPerType: packed,
  }
}

/** Per by-product, in kg × 1000: produced − carried − rejected (0 = balanced). UI-only rule. */
export function byproductBalance(
  batch: ProductionBatch,
  v: StandardizeValues,
): Record<string, { produced: number; left: number }> {
  const kg = (s: string) => valueOf(parseDecimal(s, KG_PLACES)) ?? 0
  return Object.fromEntries(
    Object.entries(v.byproducts).map(([code, row]) => {
      const produced = scaledOf(byproductRow(batch, code)?.produced_kg, KG_PLACES) ?? 0
      return [code, { produced, left: produced - kg(row.carry_kg) - kg(row.rejected_kg) }]
    }),
  )
}

export function standardizeBalanced(batch: ProductionBatch, v: StandardizeValues): boolean {
  const pieces = pieceBalance(batch, v)
  return (
    pieces.wings.left === 0 &&
    pieces.thighs.left === 0 &&
    Object.values(byproductBalance(batch, v)).every((b) => b.left === 0)
  )
}
