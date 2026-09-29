import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge, Card } from '@/components/ui'
import { useFormatDate, useLocalized } from '@/lib/format'
import type { ProductionBatch, StepNumber, UserRef } from '@/lib/types'
import { STEPS, stepData } from './api'
import { toInput } from './numbers'

function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-2 text-sm">
      <dt className="text-stone-500">{label}</dt>
      <dd className="text-right font-medium tabular-nums text-stone-900">{children}</dd>
    </div>
  )
}

function who(user: UserRef | null, system: string) {
  return !user || user.is_system ? system : user.full_name
}

const kg = (v: string | null) => (v === null ? '—' : `${toInput(v)} kg`)
const num = (v: number | null) => (v === null ? '—' : String(v))

/**
 * Read-only view of a step: finished steps, and drafts for people who can only view.
 */
export function StepSummary({ batch, step }: { batch: ProductionBatch; step: StepNumber }) {
  const { t } = useTranslation()
  const formatDate = useFormatDate()
  const localized = useLocalized()
  const data = stepData(batch, step)
  if (!data) return null
  const byproductName = (code: string) => {
    const item = batch.catalog.byproducts.find((b) => b.code === code)
    return item ? localized(item) : code
  }
  const byproducts = [...batch.byproducts].sort((a, b) => {
    const order = (c: string) => batch.catalog.byproducts.find((x) => x.code === c)?.order ?? 99
    return order(a.item_code) - order(b.item_code)
  })

  let rows: ReactNode
  if (step === 1) {
    const raw = batch.raw_material
    const kind = batch.catalog.material_kinds.find((k) => k.code === raw.material_kind)
    rows = (
      <>
        <Row label={t('production.fields.date')}>{formatDate(batch.production_date, { dateStyle: 'medium' })}</Row>
        <Row label={t('production.fields.supplier')}>
          {raw.supplier ? (
            <span className="inline-flex flex-wrap items-center justify-end gap-2">
              {raw.supplier.name}
              {!raw.supplier.is_active && <Badge tone="amber">{t('production.supplierInactive')}</Badge>}
            </span>
          ) : (
            '—'
          )}
        </Row>
        <Row label={t('production.fields.materialKind')}>
          {t(`production.materialKinds.${raw.material_kind}`, {
            defaultValue: kind ? localized(kind) : raw.material_kind,
          })}
        </Row>
        <Row label={t('production.fields.weightKg')}>{kg(raw.weight_kg)}</Row>
        <Row label={t('production.fields.quantity')}>{num(raw.quantity)}</Row>
      </>
    )
  } else if (step === 2 && batch.produced) {
    const p = batch.produced
    rows = (
      <>
        <Row label={t('production.wings')}>
          {kg(p.wings_kg)} · {t('production.pieces', { count: p.wings_count })}
        </Row>
        <Row label={t('production.thighs')}>
          {kg(p.thighs_kg)} · {t('production.pieces', { count: p.thighs_count })}
        </Row>
        {batch.computed.yield_percent && (
          <Row label={t('production.yieldLabel')}>{batch.computed.yield_percent}%</Row>
        )}
        {byproducts.map((b) => (
          <Row key={b.item_code} label={byproductName(b.item_code)}>
            {kg(b.produced_kg)}
          </Row>
        ))}
        <Row label={t('production.fields.marinadeG')}>
          {p.marinade_g === null ? '—' : `${toInput(p.marinade_g)} g`}
        </Row>
      </>
    )
  } else if (step === 3 && batch.standardize) {
    const s = batch.standardize
    rows = (
      <>
        <Row label={t('production.fields.bigPackages')}>{num(s.big_packages)}</Row>
        <Row label={t('production.fields.smallPackages')}>{num(s.small_packages)}</Row>
        <Row label={t('production.fields.rejectedWings')}>{num(s.rejected_wings)}</Row>
        <Row label={t('production.fields.rejectedThighs')}>{num(s.rejected_thighs)}</Row>
        {byproducts.map((b) => (
          <Row key={b.item_code} label={byproductName(b.item_code)}>
            {t('production.carryRejected', {
              carry: b.carry_kg === null ? '—' : toInput(b.carry_kg),
              rejected: b.rejected_kg === null ? '—' : toInput(b.rejected_kg),
            })}
          </Row>
        ))}
        {s.comment && (
          <div className="py-2 text-sm">
            <dt className="text-stone-500">{t('production.fields.comment')}</dt>
            <dd className="mt-1 whitespace-pre-wrap text-stone-800">{s.comment}</dd>
          </div>
        )}
      </>
    )
  }

  return (
    <Card
      title={t(STEPS[step - 1].labelKey)}
      actions={
        data.status === 'finished' ? (
          <Badge tone="green">{t('production.stepStatus.finished')}</Badge>
        ) : (
          <Badge tone="amber">{t('production.stepStatus.draft')}</Badge>
        )
      }
    >
      <dl className="-my-2 divide-y divide-stone-100">{rows}</dl>
      <p className="mt-3 text-xs text-stone-500">
        {data.status === 'finished'
          ? t('production.finishedBy', {
              name: who(data.finished_by, t('audit.system')),
              time: formatDate(data.finished_at),
            })
          : t('production.lastSavedBy', {
              name: who(data.updated_by, t('audit.system')),
              time: formatDate(data.updated_at),
            })}
      </p>
    </Card>
  )
}
