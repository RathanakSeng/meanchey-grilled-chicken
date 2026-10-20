import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Alert, Button, Card, ConfirmDialog, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import type { Scheduling, SchedulingWriteResult, WeekdaysInput } from '@/lib/types'
import { invalidateScheduling } from '../api'
import { AppliesFrom, ApplyToAll, isoWeekday, useDayName, useWeekdayName, WEEKDAYS } from './shared'

interface WeekdaysCardProps {
  /** The page's workplace only (`workplaces[0]`); `workplace_options` are every active one. */
  scheduling: Scheduling
  canEdit: boolean
  onDone(message: string): void
}

/** Tracked weekdays: seven toggles (Monday first), "Applies from", Save with "Apply to all
 *  workplaces" (which confirms first, naming how many other workplaces it replaces). */
export function WeekdaysCard({ scheduling, canEdit, onDone }: WeekdaysCardProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const weekday = useWeekdayName()
  const formatDay = useDayName()
  const workplace = scheduling.workplaces[0]
  const others = scheduling.workplace_options.length - 1
  const shown = workplace?.current.weekdays ?? [...WEEKDAYS]
  const today = scheduling.today
  const [days, setDays] = useState<number[]>(shown)
  const [from, setFrom] = useState(today)
  const [confirming, setConfirming] = useState(false)
  const [applyAll, setApplyAll] = useState(false)

  const key = `${workplace?.current.id}|${shown.join()}`
  useEffect(() => {
    setDays(shown)
    setFrom(today)
    setApplyAll(false)
    // Reset when the workplace or its current weekdays change.
  }, [key, today])

  const save = useMutation({
    mutationFn: async (body: WeekdaysInput) =>
      (await api.put<SchedulingWriteResult>('/attendance/scheduling/weekdays', body)).data,
    onSuccess: (result) => {
      invalidateScheduling(queryClient)
      setConfirming(false)
      const parts = [t('attendance.scheduling.weekdays.saved')]
      if (result.records_removed) parts.push(t('attendance.scheduling.recordsRemoved', { count: result.records_removed }))
      if (result.skipped_locked) parts.push(t('attendance.scheduling.skippedLocked', { count: result.skipped_locked }))
      if (result.absents_recreated) parts.push(t('attendance.scheduling.absentsRecreated', { count: result.absents_recreated }))
      onDone(parts.join(' '))
    },
  })

  const toggle = (d: number) => {
    save.reset()
    setDays((current) => (current.includes(d) ? current.filter((x) => x !== d) : [...current, d].sort()))
  }
  const todayIso = isoWeekday(today)
  // From today, untracking today removes what was already recorded today.
  // (With Apply to all, another workplace may track today: warn whenever today is left out.)
  const removesToday =
    from === today && !days.includes(todayIso) && (applyAll || shown.includes(todayIso))
  const unchanged =
    !applyAll && from === today && days.length === shown.length && days.every((d) => shown.includes(d))
  const body = (): WeekdaysInput => ({
    workplace_ids: applyAll ? 'all' : [workplace.id],
    weekdays: days,
    effective_from: from,
  })
  const confirmBody = [
    applyAll ? t('attendance.scheduling.weekdays.applyAllConfirm', { count: others, date: formatDay(from) }) : null,
    removesToday ? t('attendance.scheduling.weekdays.removesToday') : null,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <Card title={t('attendance.scheduling.weekdays.title')}>
      <div className="space-y-4">
        <div className="grid grid-cols-7 gap-1.5" role="group" aria-label={t('attendance.scheduling.weekdays.title')}>
          {WEEKDAYS.map((d) => {
            const on = days.includes(d)
            return (
              <button
                key={d}
                type="button"
                aria-pressed={on}
                disabled={!canEdit}
                onClick={() => toggle(d)}
                className={cx(
                  'min-h-[44px] rounded-lg text-sm font-semibold ring-1 ring-inset focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500',
                  on ? 'bg-brand-600 text-white ring-brand-600' : 'bg-white text-stone-600 ring-stone-300',
                  !canEdit && 'cursor-default opacity-90',
                )}
              >
                {weekday(d)}
              </button>
            )
          })}
        </div>
        <p className="text-sm text-stone-600">{t('attendance.scheduling.weekdays.hint')}</p>
        {canEdit && (
          <>
            <AppliesFrom value={from} min={today} onChange={setFrom} />
            {days.length === 0 && <Alert tone="error">{t('attendance.scheduling.weekdays.atLeastOne')}</Alert>}
            {removesToday && <Alert tone="warning">{t('attendance.scheduling.weekdays.removesToday')}</Alert>}
            {save.isError && !confirming && <Alert tone="error">{errorMessage(save.error)}</Alert>}
            <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2">
              <ApplyToAll checked={applyAll} onChange={setApplyAll} others={others} />
              <Button
                loading={save.isPending && !confirming}
                disabled={days.length === 0 || unchanged}
                onClick={() => (confirmBody ? setConfirming(true) : save.mutate(body()))}
              >
                {t('common.save')}
              </Button>
            </div>
          </>
        )}
      </div>
      {confirming && (
        <ConfirmDialog
          open
          tone={removesToday ? 'danger' : undefined}
          title={
            removesToday ? t('attendance.scheduling.weekdays.confirmTitle') : t('attendance.scheduling.applyAllTitle')
          }
          body={confirmBody}
          confirmLabel={t('common.save')}
          loading={save.isPending}
          error={save.isError ? errorMessage(save.error) : null}
          onConfirm={() => save.mutate(body())}
          onClose={() => {
            setConfirming(false)
            save.reset()
          }}
        />
      )}
    </Card>
  )
}
