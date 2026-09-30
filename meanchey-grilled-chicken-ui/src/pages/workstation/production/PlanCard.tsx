import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { usePermission } from '@/auth/usePermission'
import { Icon } from '@/components/icons'
import { Badge } from '@/components/ui'
import { paths } from '@/lib/paths'
import type { ProductionBatch } from '@/lib/types'
import { PlanStatusBadge, PlannedPacks, planStage } from '@/pages/workstation/production-plans/PlanBadge'

function OpenPlanLink({ batch }: { batch: ProductionBatch }) {
  const { t } = useTranslation()
  return (
    <Link
      to={paths.productionPlan(batch.id)}
      className="inline-flex shrink-0 items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm font-medium text-brand-700 ring-1 ring-inset ring-brand-200 hover:bg-brand-50"
    >
      <Icon name="clipboard" width={16} height={16} />
      {t('plans.openPlan')}
    </Link>
  )
}

/**
 * The packaging plan between steps 2 and 3 (read-only here): status, planned packs, and
 * **Open plan** for plan holders. Shown once step 2 has been finished.
 */
export function PlanCard({ batch }: { batch: ProductionBatch }) {
  const { t } = useTranslation()
  const canViewPlans = usePermission('production_plan.view')
  const plan = batch.plan
  if (!plan && !batch.plan_legacy) return null
  return (
    <section className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl bg-white px-4 py-3 shadow-sm ring-1 ring-stone-200">
      <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
        <Icon name="clipboard" width={18} height={18} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2 text-sm font-semibold text-stone-900">
          {t('plans.planTitle')}
          {plan ? (
            <PlanStatusBadge stage={planStage(plan.status, batch.status)} />
          ) : (
            <Badge>{t('plans.stage.legacy')}</Badge>
          )}
        </span>
        {plan && (
          <span className="block text-sm tabular-nums text-stone-600">
            <PlannedPacks big={plan.expected_big} small={plan.expected_small} />
          </span>
        )}
      </span>
      {plan && canViewPlans && <OpenPlanLink batch={batch} />}
    </section>
  )
}

/** Step 3 while the plan isn't confirmed: nothing can be entered yet. */
export function WaitingForPlan({ batch }: { batch: ProductionBatch }) {
  const { t } = useTranslation()
  const canViewPlans = usePermission('production_plan.view')
  return (
    <section className="rounded-xl bg-white p-6 text-center shadow-sm ring-1 ring-stone-200">
      <span className="mx-auto mb-3 inline-flex h-12 w-12 items-center justify-center rounded-full bg-amber-50 text-amber-700">
        <Icon name="lock" width={24} height={24} />
      </span>
      <p className="font-medium text-stone-900">{t('plans.waitingTitle')}</p>
      <p className="mx-auto mt-1 max-w-sm text-sm text-stone-500">
        {t(canViewPlans ? 'plans.waitingBodyPlanner' : 'plans.waitingBody')}
      </p>
      {canViewPlans && (
        <div className="mt-4 flex justify-center">
          <OpenPlanLink batch={batch} />
        </div>
      )}
    </section>
  )
}

/** Actual packs that differ from a set plan (null while either side isn't known yet). */
export function packsDiffer(
  batch: ProductionBatch,
  actualBig: number | null,
  actualSmall: number | null,
): boolean | null {
  const plan = batch.plan
  if (!plan || plan.expected_big === null || plan.expected_small === null) return null
  if (actualBig === null || actualSmall === null) return null
  return actualBig !== plan.expected_big || actualSmall !== plan.expected_small
}

/** Planned beside actual, per pack size, with ⚠ where they differ. */
export function PlanVsActual({
  batch,
  actualBig,
  actualSmall,
}: {
  batch: ProductionBatch
  actualBig: number | null
  actualSmall: number | null
}) {
  const { t } = useTranslation()
  const plan = batch.plan
  if (!plan) return null
  const rows = [
    { key: 'big', label: t('production.fields.bigPackages'), planned: plan.expected_big, actual: actualBig },
    { key: 'small', label: t('production.fields.smallPackages'), planned: plan.expected_small, actual: actualSmall },
  ]
  return (
    <div className="rounded-lg bg-stone-50 p-3 ring-1 ring-inset ring-stone-200">
      <p className="mb-1 text-sm font-semibold text-stone-900">{t('plans.vsActual')}</p>
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-stone-500">
          <tr>
            <th className="py-1 font-medium" />
            <th className="py-1 text-right font-medium">{t('plans.planned')}</th>
            <th className="py-1 text-right font-medium">{t('plans.actual')}</th>
            <th className="w-6 py-1" />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const differs = r.planned !== null && r.actual !== null && r.planned !== r.actual
            return (
              <tr key={r.key} className={differs ? 'text-amber-800' : 'text-stone-800'}>
                <td className="py-1">{r.label}</td>
                <td className="py-1 text-right tabular-nums">{r.planned ?? '—'}</td>
                <td className="py-1 text-right font-medium tabular-nums">{r.actual ?? '—'}</td>
                <td className="py-1 text-right">
                  {differs && (
                    <Icon name="alert" width={14} height={14} className="ml-auto text-amber-600" aria-label={t('plans.differs')} />
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
