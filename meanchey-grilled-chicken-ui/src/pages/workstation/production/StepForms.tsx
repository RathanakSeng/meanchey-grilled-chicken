import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import { Field, Input, Select, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { ClientError, getError } from '@/lib/errors'
import { useLocalized } from '@/lib/format'
import type { ProductionBatch, StepNumber } from '@/lib/types'
import { PRODUCTION_COMMENT_MAX_LENGTH } from '@/lib/types'
import { onBatchChanged, productionKeys, slugOf } from './api'
import { KG_PLACES, formatScaled, parseDecimal, scaledOf, toInput, valueOf } from './numbers'
import { SupplierPicker } from './SupplierPicker'
import { LockedValue, NumberField, StepShell } from './StepShell'
import {
  byproductBalance,
  pieceBalance,
  producedFinishErrors,
  producedFromBatch,
  producedInputErrors,
  producedPayload,
  rawFinishErrors,
  rawFromBatch,
  rawInputErrors,
  rawPayload,
  standardizeFinishErrors,
  standardizeFromBatch,
  standardizeInputErrors,
  standardizePayload,
  type Errors,
  type PieceBalance,
} from './steps'
import { useAutosaveDraft } from './useAutosaveDraft'

interface FormProps {
  batch: ProductionBatch
  /** Called with the batch after the step was finished. */
  onFinished(batch: ProductionBatch): void
}

/** Autosave wired to the batch cache, plus the Finish mutation, for one step. */
function useStep<V>(
  batch: ProductionBatch,
  step: StepNumber,
  fromBatch: (b: ProductionBatch) => V,
  toPayload: (v: V) => Record<string, unknown>,
  onFinished: (b: ProductionBatch) => void,
) {
  const queryClient = useQueryClient()
  const [values, setValues] = useState<V>(() => fromBatch(batch))
  const onSaved = useCallback(
    (b: ProductionBatch) => queryClient.setQueryData(productionKeys.batch(b.id), b),
    [queryClient],
  )
  const autosave = useAutosaveDraft<V>({
    batch,
    step,
    enabled: true,
    values,
    setValues,
    fromBatch,
    toPayload,
    onSaved,
  })
  const finish = useMutation({
    mutationFn: async () => {
      // Everything typed must be on the server first; Finish validates the saved copy.
      if (!(await autosave.flush())) throw new ClientError('PRODUCTION_UNSAVED')
      const url = `/production/${batch.id}/${slugOf(step)}/finish`
      return (await api.post<ProductionBatch>(url, { version: autosave.version() })).data
    },
    onSuccess: (b) => {
      autosave.clearDraft()
      onBatchChanged(queryClient, b)
      onFinished(b)
    },
    onError: (err) => {
      if (['PRODUCTION_CONFLICT', 'PRODUCTION_STEP_FINISHED', 'PRODUCTION_CANCELLED'].includes(getError(err).code)) {
        void queryClient.invalidateQueries({ queryKey: productionKeys.batch(batch.id) })
      }
    },
  })
  const set = (patch: Partial<V>) => setValues((v) => ({ ...v, ...patch }))
  return { values, set, setValues, autosave, finish }
}

function useByproductNames(batch: ProductionBatch) {
  const localized = useLocalized()
  return useCallback(
    (code: string) => {
      const item = batch.catalog.byproducts.find((b) => b.code === code)
      return item ? localized(item) : code
    },
    [batch.catalog.byproducts, localized],
  )
}

/** "Fill in: Supplier, Weight" for the blockers list. */
function missingBlocker(errors: Errors, label: (key: string) => string, t: TFunction) {
  const keys = Object.keys(errors)
  return keys.length ? [t('production.blockers.fillIn', { fields: keys.map(label).join(', ') })] : []
}

const orderedCodes = (batch: ProductionBatch) =>
  [...batch.catalog.byproducts].sort((a, b) => a.order - b.order).map((b) => b.code)

// --- Step 1 --------------------------------------------------------------------------------------

export function RawMaterialForm({ batch, onFinished }: FormProps) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const { values, set, autosave, finish } = useStep(batch, 1, rawFromBatch, rawPayload, onFinished)
  const errors = rawInputErrors(values)

  const label = (key: string) =>
    ({
      production_date: t('production.fields.date'),
      supplier: t('production.fields.supplier'),
      supplier_id: t('production.fields.supplier'),
      material_kind: t('production.fields.materialKind'),
      weight_kg: t('production.fields.weightKg'),
      quantity: t('production.fields.quantity'),
    })[key] ?? key

  const blockers = [
    ...missingBlocker(rawFinishErrors(values), label, t),
    ...(values.supplier?.is_active === false ? [t('production.blockers.supplierInactive')] : []),
  ]

  return (
    <StepShell
      title={t('production.steps.rawMaterial')}
      autosave={autosave}
      fieldLabel={label}
      blockers={blockers}
      onFinish={() => finish.mutate()}
      finishing={finish.isPending}
      finishError={finish.error}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('production.fields.date')}>
          {(id) => (
            <Input
              id={id}
              type="date"
              className="h-12 text-base sm:h-10 sm:text-sm"
              value={values.production_date}
              onChange={(e) => set({ production_date: e.target.value })}
            />
          )}
        </Field>
        <Field label={t('production.fields.materialKind')}>
          {(id) => (
            <Select
              id={id}
              className="h-12 text-base sm:h-10 sm:text-sm"
              value={values.material_kind}
              onChange={(e) => set({ material_kind: e.target.value })}
            >
              {batch.catalog.material_kinds.map((k) => (
                <option key={k.code} value={k.code}>
                  {t(`production.materialKinds.${k.code}`, { defaultValue: localized(k) })}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <div className="sm:col-span-2">
          <span className="mb-1 block text-sm font-medium text-stone-700">{t('production.fields.supplier')}</span>
          <SupplierPicker value={values.supplier} onChange={(supplier) => set({ supplier })} />
        </div>
        <NumberField
          label={t('production.fields.weightKg')}
          unit="kg"
          mode="decimal"
          value={values.weight_kg}
          onChange={(weight_kg) => set({ weight_kg })}
          error={errors.weight_kg}
        />
        <NumberField
          label={t('production.fields.quantity')}
          unit={t('production.units.chickens')}
          mode="numeric"
          value={values.quantity}
          onChange={(quantity) => set({ quantity })}
          error={errors.quantity}
        />
      </div>
    </StepShell>
  )
}

// --- Step 2 --------------------------------------------------------------------------------------

export function ProducedForm({ batch, onFinished }: FormProps) {
  const { t } = useTranslation()
  const name = useByproductNames(batch)
  const { values, set, autosave, finish } = useStep(
    batch,
    2,
    producedFromBatch,
    producedPayload,
    onFinished,
  )
  const errors = producedInputErrors(values)
  const quantity = batch.raw_material.quantity ?? 0
  const perChicken = batch.catalog.material_kinds.find((k) => k.code === batch.raw_material.material_kind)

  const label = (key: string) => {
    if (key.startsWith('byproducts.')) return name(key.split('.')[1])
    return (
      {
        wings_kg: t('production.fields.wingsKg'),
        thighs_kg: t('production.fields.thighsKg'),
        marinade_g: t('production.fields.marinadeG'),
      }[key] ?? key
    )
  }

  // Live yield: (wings + thighs) ÷ raw weight.
  const raw = scaledOf(batch.raw_material.weight_kg, KG_PLACES)
  const wings = valueOf(parseDecimal(values.wings_kg, KG_PLACES))
  const thighs = valueOf(parseDecimal(values.thighs_kg, KG_PLACES))
  const yieldPercent =
    raw && wings !== null && thighs !== null ? (((wings + thighs) / raw) * 100).toFixed(1) : null

  return (
    <StepShell
      title={t('production.steps.produced')}
      autosave={autosave}
      fieldLabel={label}
      blockers={missingBlocker(producedFinishErrors(values), label, t)}
      onFinish={() => finish.mutate()}
      finishing={finish.isPending}
      finishError={finish.error}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <NumberField
          label={t('production.fields.wingsKg')}
          unit="kg"
          mode="decimal"
          value={values.wings_kg}
          onChange={(wings_kg) => set({ wings_kg })}
          error={errors.wings_kg}
        />
        <LockedValue
          label={t('production.fields.wingsCount')}
          value={t('production.pieces', { count: batch.produced?.wings_count ?? 0 })}
          hint={t('production.perChicken', { count: perChicken?.wings_per_unit ?? 2, chickens: quantity })}
        />
        <NumberField
          label={t('production.fields.thighsKg')}
          unit="kg"
          mode="decimal"
          value={values.thighs_kg}
          onChange={(thighs_kg) => set({ thighs_kg })}
          error={errors.thighs_kg}
        />
        <LockedValue
          label={t('production.fields.thighsCount')}
          value={t('production.pieces', { count: batch.produced?.thighs_count ?? 0 })}
          hint={t('production.perChicken', { count: perChicken?.thighs_per_unit ?? 2, chickens: quantity })}
        />
      </div>
      {yieldPercent && (
        <p className="text-sm text-stone-600">{t('production.yield', { percent: yieldPercent })}</p>
      )}

      <fieldset>
        <legend className="mb-2 text-sm font-semibold text-stone-900">{t('production.byproductsTitle')}</legend>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {orderedCodes(batch).map((code) => (
            <NumberField
              key={code}
              label={name(code)}
              unit="kg"
              mode="decimal"
              value={values.byproducts[code] ?? ''}
              onChange={(kg) => set({ byproducts: { ...values.byproducts, [code]: kg } })}
              error={errors[`byproducts.${code}`]}
            />
          ))}
        </div>
      </fieldset>

      <div className="sm:max-w-xs">
        <NumberField
          label={t('production.fields.marinadeG')}
          unit="g"
          mode="decimal"
          value={values.marinade_g}
          onChange={(marinade_g) => set({ marinade_g })}
          error={errors.marinade_g}
        />
      </div>
    </StepShell>
  )
}

// --- Step 3 --------------------------------------------------------------------------------------

function BalanceMeter({ label, balance }: { label: string; balance: PieceBalance }) {
  const { t } = useTranslation()
  const pct = balance.expected > 0 ? Math.min(100, (balance.assigned / balance.expected) * 100) : 0
  const tone = balance.left === 0 ? 'green' : balance.left < 0 ? 'red' : 'amber'
  return (
    <div className="rounded-lg bg-stone-50 p-3 ring-1 ring-inset ring-stone-200">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="font-medium text-stone-800">{label}</span>
        <span className="tabular-nums text-stone-500">
          {balance.assigned} / {balance.expected}
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-stone-200">
        <div
          className={cx(
            'h-full rounded-full transition-all',
            tone === 'green' ? 'bg-green-500' : tone === 'red' ? 'bg-red-500' : 'bg-amber-400',
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p
        className={cx(
          'mt-1 text-xs font-medium',
          tone === 'green' ? 'text-green-700' : tone === 'red' ? 'text-red-600' : 'text-amber-700',
        )}
      >
        {balance.left === 0
          ? t('production.balance.done')
          : balance.left > 0
            ? t('production.balance.left', { count: balance.left })
            : t('production.balance.tooMany', { count: -balance.left })}
      </p>
    </div>
  )
}

export function StandardizeForm({ batch, onFinished }: FormProps) {
  const { t } = useTranslation()
  const name = useByproductNames(batch)
  const { values, set, autosave, finish } = useStep(
    batch,
    3,
    standardizeFromBatch,
    standardizePayload,
    onFinished,
  )
  const errors = standardizeInputErrors(values)
  const pieces = pieceBalance(batch, values)
  const byproducts = byproductBalance(batch, values)
  const count = (s: string) => (/^\d+$/.test(s.trim()) ? Number(s) : 0)

  const label = (key: string) => {
    const [head, code, field] = key.split('.')
    if (head === 'byproducts' && code) {
      return field
        ? `${name(code)} (${t(field === 'carry_kg' ? 'production.fields.carryKg' : 'production.fields.rejectedKg')})`
        : name(code)
    }
    return (
      {
        big_packages: t('production.fields.bigPackages'),
        small_packages: t('production.fields.smallPackages'),
        rejected_wings: t('production.fields.rejectedWings'),
        rejected_thighs: t('production.fields.rejectedThighs'),
        comment: t('production.fields.comment'),
      }[key] ?? key
    )
  }

  const kg = (scaled: number) => toInput(formatScaled(Math.abs(scaled), KG_PLACES))
  const blockers = [
    ...missingBlocker(standardizeFinishErrors(values), label, t),
    ...(pieces.wings.left !== 0 ? [t('production.blockers.wings')] : []),
    ...(pieces.thighs.left !== 0 ? [t('production.blockers.thighs')] : []),
    ...Object.entries(byproducts)
      .filter(([, b]) => b.left !== 0)
      .map(([code]) => t('production.blockers.byproduct', { name: name(code) })),
  ]

  return (
    <StepShell
      title={t('production.steps.standardize')}
      autosave={autosave}
      fieldLabel={label}
      blockers={blockers}
      onFinish={() => finish.mutate()}
      finishing={finish.isPending}
      finishError={finish.error}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <NumberField
          label={t('production.fields.bigPackages')}
          mode="numeric"
          value={values.big_packages}
          onChange={(big_packages) => set({ big_packages })}
          error={errors.big_packages}
          hint={t('production.bigHint', { count: count(values.big_packages) * 2 })}
        />
        <NumberField
          label={t('production.fields.smallPackages')}
          mode="numeric"
          value={values.small_packages}
          onChange={(small_packages) => set({ small_packages })}
          error={errors.small_packages}
          hint={t('production.smallHint', { count: count(values.small_packages) })}
        />
        <NumberField
          label={t('production.fields.rejectedWings')}
          mode="numeric"
          value={values.rejected_wings}
          onChange={(rejected_wings) => set({ rejected_wings })}
          error={errors.rejected_wings}
        />
        <NumberField
          label={t('production.fields.rejectedThighs')}
          mode="numeric"
          value={values.rejected_thighs}
          onChange={(rejected_thighs) => set({ rejected_thighs })}
          error={errors.rejected_thighs}
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <BalanceMeter label={t('production.wings')} balance={pieces.wings} />
        <BalanceMeter label={t('production.thighs')} balance={pieces.thighs} />
      </div>

      <fieldset>
        <legend className="mb-1 text-sm font-semibold text-stone-900">{t('production.byproductsTitle')}</legend>
        <p className="mb-2 text-xs text-stone-500">{t('production.byproductsHint')}</p>
        <ul className="space-y-3">
          {orderedCodes(batch).map((code) => {
            const row = values.byproducts[code] ?? { carry_kg: '', rejected_kg: '' }
            const balance = byproducts[code]
            const update = (patch: Partial<typeof row>) =>
              set({ byproducts: { ...values.byproducts, [code]: { ...row, ...patch } } })
            return (
              <li key={code} className="rounded-lg p-3 ring-1 ring-inset ring-stone-200">
                <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <span className="font-medium text-stone-900">{name(code)}</span>
                  <span className="text-stone-500">
                    {t('production.producedKg', { kg: kg(balance?.produced ?? 0) })}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <NumberField
                    compact
                    label={t('production.fields.carryKg')}
                    unit="kg"
                    mode="decimal"
                    value={row.carry_kg}
                    onChange={(carry_kg) => update({ carry_kg })}
                    error={errors[`byproducts.${code}.carry_kg`]}
                  />
                  <NumberField
                    compact
                    label={t('production.fields.rejectedKg')}
                    unit="kg"
                    mode="decimal"
                    value={row.rejected_kg}
                    onChange={(rejected_kg) => update({ rejected_kg })}
                    error={errors[`byproducts.${code}.rejected_kg`]}
                  />
                </div>
                {balance && (
                  <p
                    className={cx(
                      'mt-2 text-xs font-medium',
                      balance.left === 0 ? 'text-green-700' : balance.left < 0 ? 'text-red-600' : 'text-amber-700',
                    )}
                  >
                    {balance.left === 0
                      ? t('production.balance.kgDone')
                      : balance.left > 0
                        ? t('production.balance.kgLeft', { kg: kg(balance.left) })
                        : t('production.balance.kgTooMuch', { kg: kg(balance.left) })}
                  </p>
                )}
              </li>
            )
          })}
        </ul>
      </fieldset>

      <Field label={t('production.fields.comment')}>
        {(id) => (
          <textarea
            id={id}
            rows={3}
            maxLength={PRODUCTION_COMMENT_MAX_LENGTH}
            value={values.comment}
            onChange={(e) => set({ comment: e.target.value })}
            className="block w-full rounded-lg border-0 bg-white px-3 py-2 text-base text-stone-900 shadow-sm ring-1 ring-inset ring-stone-300 placeholder:text-stone-400 focus:ring-2 focus:ring-inset focus:ring-brand-500 sm:text-sm"
          />
        )}
      </Field>
    </StepShell>
  )
}

