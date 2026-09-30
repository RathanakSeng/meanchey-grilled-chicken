import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { usePermission } from '@/auth/usePermission'
import { Icon } from '@/components/icons'
import { Alert, Button, Card, ConfirmDialog, Field, PageHeader, Spinner, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { getError, useErrorMessage } from '@/lib/errors'
import { useFormatDate, useFormatDay, useLocalized } from '@/lib/format'
import { paths } from '@/lib/paths'
import { PLAN_NOTE_MAX_LENGTH, type PlanDetail, type UserRef } from '@/lib/types'
import { productionKeys } from '@/pages/workstation/production/api'
import { toInput } from '@/pages/workstation/production/numbers'
import { NumberField } from '@/pages/workstation/production/StepShell'
import { fetchPlan, invalidatePlans, planKeys, plannedPieces } from './api'
import { PlanStatusBadge, planStage } from './PlanBadge'

const COUNT = /^\d+$/

interface Values {
  big: string
  small: string
  note: string
}

function fromPlan(detail: PlanDetail): Values {
  const plan = detail.plan
  return {
    big: plan?.expected_big === null || plan?.expected_big === undefined ? '' : String(plan.expected_big),
    small: plan?.expected_small === null || plan?.expected_small === undefined ? '' : String(plan.expected_small),
    note: plan?.note ?? '',
  }
}

/** A count from the input: null when empty, NaN when not a whole number. */
function parseCount(value: string): number | null {
  const v = value.trim()
  if (!v) return null
  return COUNT.test(v) ? Number(v) : Number.NaN
}

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

/** "Uses 296 of 300 wings · 296 of 300 thighs"; red when the plan needs more than was produced. */
function UsageMeter({ planned, wings, thighs }: { planned: number; wings: number; thighs: number }) {
  const { t } = useTranslation()
  const over = planned > wings || planned > thighs
  const max = Math.max(1, Math.min(wings, thighs))
  return (
    <div className="rounded-lg bg-stone-50 p-3 ring-1 ring-inset ring-stone-200">
      <p className={cx('text-sm font-medium tabular-nums', over ? 'text-red-600' : 'text-stone-800')}>
        {t('plans.usage', { planned, wings, thighs })}
      </p>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-stone-200">
        <div
          className={cx('h-full rounded-full transition-all', over ? 'bg-red-500' : 'bg-brand-500')}
          style={{ width: `${Math.min(100, (planned / max) * 100)}%` }}
        />
      </div>
      {over && <p className="mt-1 text-xs font-medium text-red-600">{t('plans.exceeds')}</p>}
    </div>
  )
}

/**
 * One packaging plan: step 2's output (read-only) and the planned 4-piece / 2-piece packs.
 * With `production_plan.manage` and while editable: Save and Confirm plan (which step 3 waits for).
 * Writes send the batch `version`; on PRODUCTION_CONFLICT the plan is reloaded with a notice.
 */
export function PlanPage() {
  const { t } = useTranslation()
  const { batchId = '' } = useParams()
  const queryClient = useQueryClient()
  const formatDate = useFormatDate()
  const formatDay = useFormatDay()
  const localized = useLocalized()
  const errorMessage = useErrorMessage()
  const canManage = usePermission('production_plan.manage')
  const canViewBatch = usePermission('production.view')

  const query = useQuery({ queryKey: planKeys.detail(batchId), queryFn: () => fetchPlan(batchId) })
  const detail = query.data

  const [values, setValues] = useState<Values>({ big: '', small: '', note: '' })
  const [dirty, setDirty] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [confirming, setConfirming] = useState(false)

  // Take the server's values whenever they change and nothing is being edited.
  useEffect(() => {
    if (detail && !dirty) setValues(fromPlan(detail))
  }, [detail?.version])

  const set = (patch: Partial<Values>) => {
    setValues((v) => ({ ...v, ...patch }))
    setDirty(true)
  }

  const onSaved = (d: PlanDetail) => {
    queryClient.setQueryData(planKeys.detail(batchId), d)
    invalidatePlans(queryClient)
    // The batch (its plan card, step 3 lock) and the production list's "Waiting for plan".
    void queryClient.invalidateQueries({ queryKey: productionKeys.batch(batchId) })
    void queryClient.invalidateQueries({ queryKey: productionKeys.list })
    setValues(fromPlan(d))
    setDirty(false)
    setConflict(false)
  }
  const onError = (err: unknown) => {
    if (['PRODUCTION_CONFLICT', 'PRODUCTION_PLAN_LOCKED', 'PRODUCTION_CANCELLED'].includes(getError(err).code)) {
      setConflict(getError(err).code === 'PRODUCTION_CONFLICT')
      setDirty(false)
      void query.refetch()
    }
  }

  const big = parseCount(values.big)
  const small = parseCount(values.small)
  const note = values.note.trim()
  const body = () => ({ expected_big: big, expected_small: small, note: note || null })

  const save = useMutation({
    mutationFn: async () =>
      (await api.patch<PlanDetail>(`/production-plans/${batchId}`, { version: detail?.version, ...body() })).data,
    onSuccess: onSaved,
    onError,
  })
  const confirm = useMutation({
    mutationFn: async () => {
      let version = detail?.version
      if (dirty) {
        version = (await api.patch<PlanDetail>(`/production-plans/${batchId}`, { version, ...body() })).data.version
      }
      return (await api.post<PlanDetail>(`/production-plans/${batchId}/confirm`, { version })).data
    },
    onSuccess: (d) => {
      setConfirming(false)
      onSaved(d)
    },
    onError: (err) => {
      setConfirming(false)
      onError(err)
    },
  })

  if (query.isPending) {
    return (
      <div className="flex justify-center py-16 text-brand-600">
        <Spinner />
      </div>
    )
  }
  if (!detail) {
    return (
      <>
        <PageHeader back={paths.productionPlans} title={t('plans.title')} />
        <Alert tone="error">{errorMessage(query.error)}</Alert>
      </>
    )
  }

  const plan = detail.plan
  const produced = detail.produced
  const editable = canManage && detail.editable
  const invalid = Number.isNaN(big) || Number.isNaN(small)
  const planned = plannedPieces(Number.isNaN(big) ? 0 : big, Number.isNaN(small) ? 0 : small)
  const exceeds = produced ? planned > produced.wings_count || planned > produced.thighs_count : false
  const confirmed = plan?.status === 'confirmed'
  // A confirmed plan can't lose a value; confirming needs both.
  const canSave = dirty && !invalid && !exceeds && !(confirmed && (big === null || small === null))
  const canConfirm = !invalid && !exceeds && big !== null && small !== null
  const busy = save.isPending || confirm.isPending
  const actual = detail.standardize?.status === 'finished' ? detail.standardize : null

  return (
    <>
      <PageHeader
        back={paths.productionPlans}
        title={<span className="tabular-nums">{detail.code}</span>}
        subtitle={
          <span className="flex flex-wrap items-center gap-1.5">
            {plan && <PlanStatusBadge stage={planStage(plan.status, detail.batch_status)} />}
            {produced?.production_date && (
              <span className="rounded-full bg-stone-100 px-2 py-0.5 text-xs tabular-nums text-stone-700">
                {t('production.datesShort.production')}{' '}
                {formatDay(produced.production_date, { day: 'numeric', month: 'short' })}
              </span>
            )}
            {detail.supplier && <span className="text-stone-500">{detail.supplier.name}</span>}
          </span>
        }
        actions={
          canViewBatch ? (
            <Link
              to={paths.productionBatch(detail.batch_id, detail.batch_status === 'completed' ? 3 : undefined)}
              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-brand-700 ring-1 ring-inset ring-brand-200 hover:bg-brand-50"
            >
              <Icon name="chicken" width={16} height={16} />
              {t('plans.openBatch')}
            </Link>
          ) : undefined
        }
      />

      {conflict && (
        <Alert tone="warning" className="mb-4">
          {t('plans.conflict')}
        </Alert>
      )}
      {detail.batch_status === 'cancelled' && (
        <Alert tone="warning" className="mb-4">
          {t('production.cancelledNotice')}
        </Alert>
      )}
      {detail.plan_legacy && (
        <Alert className="mb-4">{t('plans.legacy')}</Alert>
      )}
      {!plan && !detail.plan_legacy && <Alert className="mb-4">{t('plans.notYet')}</Alert>}
      {plan && !detail.editable && detail.batch_status === 'in_progress' && produced?.status !== 'finished' && (
        <Alert className="mb-4">{t('plans.stepTwoReopened')}</Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t('plans.producedTitle')}>
          {produced ? (
            <dl className="-my-2 divide-y divide-stone-100">
              <Row label={t('production.wings')}>
                {produced.wings_kg === null ? '—' : `${toInput(produced.wings_kg)} kg`} ·{' '}
                {t('production.pieces', { count: produced.wings_count })}
              </Row>
              <Row label={t('production.thighs')}>
                {produced.thighs_kg === null ? '—' : `${toInput(produced.thighs_kg)} kg`} ·{' '}
                {t('production.pieces', { count: produced.thighs_count })}
              </Row>
              {produced.byproducts.map((b) => (
                <Row key={b.item_code} label={localized(b)}>
                  {b.produced_kg === null ? '—' : `${toInput(b.produced_kg)} kg`}
                </Row>
              ))}
              <Row label={t('production.fields.marinadeG')}>
                {produced.marinade_g === null ? '—' : `${toInput(produced.marinade_g)} g`}
              </Row>
              <Row label={t('production.fields.quantity')}>{detail.quantity ?? '—'}</Row>
            </dl>
          ) : (
            <p className="text-sm text-stone-500">{t('plans.notYet')}</p>
          )}
        </Card>

        <Card
          title={t('plans.planTitle')}
          actions={plan ? <PlanStatusBadge stage={planStage(plan.status, detail.batch_status)} /> : undefined}
        >
          {plan && editable && produced ? (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <NumberField
                  label={t('production.fields.bigPackages')}
                  mode="numeric"
                  value={values.big}
                  onChange={(v) => set({ big: v })}
                  error={Number.isNaN(big) ? 'invalidCount' : null}
                  hint={t('production.bigHint', { count: 2 * (Number.isNaN(big) ? 0 : (big ?? 0)) })}
                />
                <NumberField
                  label={t('production.fields.smallPackages')}
                  mode="numeric"
                  value={values.small}
                  onChange={(v) => set({ small: v })}
                  error={Number.isNaN(small) ? 'invalidCount' : null}
                  hint={t('production.smallHint', { count: Number.isNaN(small) ? 0 : (small ?? 0) })}
                />
              </div>
              <UsageMeter planned={planned} wings={produced.wings_count} thighs={produced.thighs_count} />
              <Field label={t('plans.note')}>
                {(id) => (
                  <textarea
                    id={id}
                    rows={2}
                    maxLength={PLAN_NOTE_MAX_LENGTH}
                    value={values.note}
                    onChange={(e) => set({ note: e.target.value })}
                    className="block w-full rounded-lg border-0 bg-white px-3 py-2 text-base text-stone-900 shadow-sm ring-1 ring-inset ring-stone-300 focus:ring-2 focus:ring-inset focus:ring-brand-500 sm:text-sm"
                  />
                )}
              </Field>
              {(save.isError || confirm.isError) && (
                <Alert tone="error">{errorMessage(save.error ?? confirm.error)}</Alert>
              )}
              <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                <Button variant="secondary" disabled={!canSave || busy} loading={save.isPending} onClick={() => save.mutate()}>
                  {t('common.save')}
                </Button>
                {/* A confirmed plan is edited with Save and stays confirmed. */}
                {!confirmed && (
                  <Button disabled={!canConfirm || busy} loading={confirm.isPending} onClick={() => setConfirming(true)}>
                    <Icon name="check" width={18} height={18} />
                    {t('plans.confirm')}
                  </Button>
                )}
              </div>
            </div>
          ) : plan ? (
            <dl className="-my-2 divide-y divide-stone-100">
              <Row label={t('production.fields.bigPackages')}>{plan.expected_big ?? '—'}</Row>
              <Row label={t('production.fields.smallPackages')}>{plan.expected_small ?? '—'}</Row>
              {actual && (
                <>
                  <Row label={t('plans.actualBig')}>{actual.big_packages ?? '—'}</Row>
                  <Row label={t('plans.actualSmall')}>{actual.small_packages ?? '—'}</Row>
                </>
              )}
              {plan.note && <Row label={t('plans.note')}>{plan.note}</Row>}
              {actual?.comment && <Row label={t('production.fields.comment')}>{actual.comment}</Row>}
            </dl>
          ) : (
            <p className="text-sm text-stone-500">{t(detail.plan_legacy ? 'plans.legacy' : 'plans.notYet')}</p>
          )}
          {plan && (
            <p className="mt-3 text-xs text-stone-500">
              {confirmed
                ? t('plans.confirmedBy', {
                    name: who(plan.confirmed_by, t('audit.system')),
                    time: formatDate(plan.confirmed_at),
                  })
                : t('plans.waitingNote')}
              {confirmed && editable && <span className="block">{t('plans.confirmedEditable')}</span>}
            </p>
          )}
        </Card>
      </div>

      <ConfirmDialog
        open={confirming}
        title={t('plans.confirmTitle')}
        body={t('plans.confirmBody', { big: big ?? 0, small: small ?? 0 })}
        confirmLabel={t('plans.confirm')}
        loading={confirm.isPending}
        onConfirm={() => confirm.mutate()}
        onClose={() => setConfirming(false)}
      />
    </>
  )
}
