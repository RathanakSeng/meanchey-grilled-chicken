import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams, useSearchParams } from 'react-router-dom'
import { usePermission } from '@/auth/usePermission'
import { ActionMenu, type ActionMenuItem } from '@/components/ActionMenu'
import { Icon } from '@/components/icons'
import { Sheet } from '@/components/Sheet'
import { Alert, Button, ConfirmDialog, Field, PageHeader, Spinner, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { getError, useErrorMessage } from '@/lib/errors'
import { useFormatDate, useFormatDay } from '@/lib/format'
import { paths } from '@/lib/paths'
import { CANCEL_REASON_MAX_LENGTH, type ProductionBatch, type StepNumber } from '@/lib/types'
import {
  STEPS,
  canReopenStep,
  onBatchChanged,
  planConfirmed,
  productionKeys,
  slugOf,
  stepData,
  stepDate,
} from './api'
import { BatchStatusBadge } from './badges'
import { PlanCard, WaitingForPlan } from './PlanCard'
import { ProducedForm, RawMaterialForm, StandardizeForm } from './StepForms'
import { StepSummary } from './StepSummaries'

function Stepper({
  batch,
  selected,
  onSelect,
}: {
  batch: ProductionBatch
  selected: StepNumber
  onSelect(step: StepNumber): void
}) {
  const { t } = useTranslation()
  const formatDay = useFormatDay()
  return (
    <ol className="mb-4 grid grid-cols-3 gap-2">
      {STEPS.map(({ n, labelKey }) => {
        const data = stepData(batch, n)
        const finished = data?.status === 'finished'
        const day = stepDate(batch, n)
        const active = n === selected
        return (
          <li key={n}>
            <button
              type="button"
              disabled={!data}
              onClick={() => onSelect(n)}
              aria-current={active ? 'step' : undefined}
              className={cx(
                'flex h-full w-full flex-col items-center gap-1 rounded-xl px-2 py-2.5 text-center ring-1 transition sm:flex-row sm:gap-2 sm:text-left',
                active ? 'bg-brand-50 ring-2 ring-brand-500' : 'bg-white ring-stone-200 hover:ring-stone-300',
                !data && 'cursor-not-allowed opacity-50 hover:ring-stone-200',
              )}
            >
              <span
                className={cx(
                  'inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-semibold',
                  finished ? 'bg-green-600 text-white' : active ? 'bg-brand-600 text-white' : 'bg-stone-100 text-stone-600',
                )}
              >
                {finished ? <Icon name="check" width={16} height={16} /> : n}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-xs font-semibold text-stone-900 sm:text-sm">{t(labelKey)}</span>
                {/* One status line: "Finished · 27 Sept" / "Draft", so every card has the same height. */}
                <span className="hidden truncate text-xs text-stone-500 sm:block">
                  {t(`production.stepStatus.${data ? data.status : 'pending'}`)}
                  {day && <span className="tabular-nums"> · {formatDay(day, { day: 'numeric', month: 'short' })}</span>}
                </span>
                {/* Phones: the ✓ is the status; the date sits under the name (cards stretch evenly). */}
                {day && (
                  <span className="block text-xs tabular-nums text-stone-500 sm:hidden">
                    {formatDay(day, { day: 'numeric', month: 'short' })}
                  </span>
                )}
              </span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}

/** Header chips: "នាំចូល 28 Sept · ផលិត 29 Sept · វេចខ្ចប់ —", or "Started 29 Sept" before any step
 * is finished. Dates are recorded by the server at Finish. */
function BatchDates({ batch }: { batch: ProductionBatch }) {
  const { t } = useTranslation()
  const formatDate = useFormatDate()
  const formatDay = useFormatDay()
  const short = { day: 'numeric', month: 'short' } as const
  if (!batch.raw_material.import_date) {
    return (
      <span className="rounded-full bg-stone-100 px-2 py-0.5 text-xs text-stone-600">
        {t('production.started', { date: formatDate(batch.created_at, short) })}
      </span>
    )
  }
  return (
    <>
      {STEPS.map(({ n, dateKey, dateShortKey }) => {
        const day = stepDate(batch, n)
        return (
          <span
            key={n}
            title={t(dateKey)}
            className={cx(
              'rounded-full bg-stone-100 px-2 py-0.5 text-xs tabular-nums',
              day ? 'text-stone-700' : 'text-stone-400',
            )}
          >
            {t(dateShortKey)} {day ? formatDay(day, short) : '—'}
          </span>
        )
      })}
    </>
  )
}

/**
 * One batch: header (code, status, step dates, ⋮ menu), the 1·2·3 stepper and the selected step
 * (`?step=`): its form while it's a draft the user may record, otherwise a summary. The ⋮ menu
 * has **Reopen <step>** for every finished step (`production.update`), which reopens it and every
 * later finished step in one go, and **Cancel batch** (`production.delete`, GM only).
 */
export function ProductionBatchPage() {
  const { t } = useTranslation()
  const { batchId = '' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const formatDate = useFormatDate()
  const errorMessage = useErrorMessage()
  const canRecord = usePermission('production.create')
  const canReopen = usePermission('production.update')
  const canCancel = usePermission('production.delete')

  const query = useQuery({
    queryKey: productionKeys.batch(batchId),
    queryFn: async () => (await api.get<ProductionBatch>(`/production/${batchId}`)).data,
  })
  const batch = query.data

  const [reopenStep, setReopenStep] = useState<StepNumber | null>(null)
  const [cancelOpen, setCancelOpen] = useState(false)
  const [reason, setReason] = useState('')

  const selectStep = (step: StepNumber) =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set('step', String(step))
        return next
      },
      { replace: true },
    )

  const onStale = (err: unknown) => {
    if (['PRODUCTION_CONFLICT', 'PRODUCTION_CANCELLED'].includes(getError(err).code)) {
      void queryClient.invalidateQueries({ queryKey: productionKeys.batch(batchId) })
    }
  }
  const reopen = useMutation({
    mutationFn: async (step: StepNumber) =>
      (
        await api.post<ProductionBatch>(`/production/${batchId}/${slugOf(step)}/reopen`, {
          version: batch?.version,
        })
      ).data,
    onSuccess: (b, step) => {
      onBatchChanged(queryClient, b)
      setReopenStep(null)
      selectStep(step)
    },
    onError: onStale,
  })
  const cancel = useMutation({
    mutationFn: async () =>
      (
        await api.post<ProductionBatch>(`/production/${batchId}/cancel`, {
          version: batch?.version,
          reason: reason.trim(),
        })
      ).data,
    onSuccess: (b) => {
      onBatchChanged(queryClient, b)
      setCancelOpen(false)
    },
    onError: onStale,
  })

  if (query.isPending) {
    return (
      <div className="flex justify-center py-16 text-brand-600">
        <Spinner />
      </div>
    )
  }
  if (!batch) {
    return (
      <>
        <PageHeader back={paths.production} title={t('production.title')} />
        <Alert tone="error">{errorMessage(query.error)}</Alert>
      </>
    )
  }

  const requested = Number(searchParams.get('step')) as StepNumber
  const selected: StepNumber =
    [1, 2, 3].includes(requested) && stepData(batch, requested) ? requested : batch.current_step
  const data = stepData(batch, selected)
  const editable = data?.status === 'draft' && batch.status === 'in_progress' && canRecord
  // Step 3 waits for a confirmed packaging plan (the API refuses saves until then).
  const waitingForPlan =
    selected === 3 && data?.status === 'draft' && batch.status === 'in_progress' && !planConfirmed(batch)

  const actions: ActionMenuItem[] = [
    ...(canReopen
      ? STEPS.filter(({ n }) => canReopenStep(batch, n)).map(({ n, labelKey }) => ({
          key: `reopen-${n}`,
          label: t('production.reopenStep', { step: t(labelKey) }),
          icon: 'restore' as const,
          onSelect: () => {
            reopen.reset()
            setReopenStep(n)
          },
        }))
      : []),
    // Cancelling is general-manager only (production.delete).
    ...(canCancel && batch.status === 'in_progress'
      ? [
          {
            key: 'cancel',
            label: t('production.cancelBatch'),
            icon: 'archive' as const,
            tone: 'danger' as const,
            onSelect: () => {
              cancel.reset()
              setReason('')
              setCancelOpen(true)
            },
          },
        ]
      : []),
  ]

  /** "Produced and Standardize will go back to draft …", from the API's `reopens_steps`. */
  const reopenBody = (step: StepNumber) => {
    const later = (stepData(batch, step)?.reopens_steps ?? []).filter((n) => n !== step)
    const names = later.map((n) => t(STEPS[n - 1].labelKey))
    const text = later.length
      ? t('production.reopenConfirmLater', {
          steps:
            names.length > 1
              ? t('production.andList', {
                  first: names.slice(0, -1).join(', '),
                  last: names[names.length - 1],
                })
              : names[0],
        })
      : t('production.reopenConfirmSelf')
    return batch.status === 'completed' ? `${text} ${t('production.reopenConfirmCompleted')}` : text
  }

  const onFinished = (b: ProductionBatch) => {
    if (b.status !== 'completed') selectStep(b.current_step)
  }

  return (
    <>
      <PageHeader
        back={paths.production}
        title={<span className="tabular-nums">{batch.code}</span>}
        subtitle={
          <span className="flex flex-wrap items-center gap-1.5">
            <BatchStatusBadge status={batch.status} />
            <BatchDates batch={batch} />
          </span>
        }
        actions={<ActionMenu items={actions} label={t('production.actions')} />}
      />

      {batch.status === 'cancelled' && (
        <Alert tone="warning" className="mb-4">
          <p className="font-medium">{t('production.cancelledNotice')}</p>
          {batch.cancel_reason && <p className="mt-0.5">{batch.cancel_reason}</p>}
        </Alert>
      )}
      {batch.status === 'completed' && (
        <Alert tone="success" className="mb-4">
          {t('production.completedNotice', { time: formatDate(batch.completed_at) })}
        </Alert>
      )}
      {!canRecord && batch.status === 'in_progress' && (
        <Alert className="mb-4">{t('production.readOnlyNotice')}</Alert>
      )}

      <Stepper batch={batch} selected={selected} onSelect={selectStep} />
      <PlanCard batch={batch} />

      {waitingForPlan ? (
        <WaitingForPlan batch={batch} />
      ) : editable ? (
        selected === 1 ? (
          <RawMaterialForm key={`${batch.id}-1`} batch={batch} onFinished={onFinished} />
        ) : selected === 2 ? (
          <ProducedForm key={`${batch.id}-2`} batch={batch} onFinished={onFinished} />
        ) : (
          <StandardizeForm key={`${batch.id}-3`} batch={batch} onFinished={onFinished} />
        )
      ) : (
        <StepSummary batch={batch} step={selected} />
      )}

      <ConfirmDialog
        open={reopenStep !== null}
        title={
          reopenStep
            ? t('production.reopenConfirmTitle', { step: t(STEPS[reopenStep - 1].labelKey) })
            : ''
        }
        body={reopenStep ? reopenBody(reopenStep) : null}
        confirmLabel={t('production.reopen')}
        loading={reopen.isPending}
        error={reopen.isError ? errorMessage(reopen.error) : null}
        onConfirm={() => reopenStep && reopen.mutate(reopenStep)}
        onClose={() => setReopenStep(null)}
      />

      <Sheet
        open={cancelOpen}
        title={t('production.cancelBatch')}
        onClose={() => setCancelOpen(false)}
        busy={cancel.isPending}
        footer={
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="secondary" onClick={() => setCancelOpen(false)} disabled={cancel.isPending}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="danger"
              loading={cancel.isPending}
              disabled={!reason.trim()}
              onClick={() => cancel.mutate()}
            >
              {t('production.cancelBatch')}
            </Button>
          </div>
        }
      >
        <p className="mb-3 text-sm text-stone-600">{t('production.cancelBody', { code: batch.code })}</p>
        <Field label={t('production.cancelReason')}>
          {(id) => (
            <textarea
              id={id}
              rows={3}
              autoFocus
              maxLength={CANCEL_REASON_MAX_LENGTH}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="block w-full rounded-lg border-0 bg-white px-3 py-2 text-base text-stone-900 shadow-sm ring-1 ring-inset ring-stone-300 focus:ring-2 focus:ring-inset focus:ring-brand-500 sm:text-sm"
            />
          )}
        </Field>
        {cancel.isError && (
          <Alert tone="error" className="mt-3">
            {errorMessage(cancel.error)}
          </Alert>
        )}
      </Sheet>
    </>
  )
}
