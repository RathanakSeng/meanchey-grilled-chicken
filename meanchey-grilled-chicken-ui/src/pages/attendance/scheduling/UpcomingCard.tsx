import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Card, ConfirmDialog } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import type { AttendanceRules, ScheduleVersion, Scheduling } from '@/lib/types'
import { invalidateScheduling, useShiftName } from '../api'
import { useDayName, useWeekdayName } from './shared'

const RULE_LABELS: Record<keyof AttendanceRules, string> = {
  open_before_min: 'attendance.shiftsPage.openBefore',
  absent_after_min: 'attendance.shiftsPage.absentAfter',
  checkout_window_min: 'attendance.shiftsPage.checkoutWindow',
  reminders_enabled: 'attendance.shiftsPage.reminders',
  count_early_checkin: 'attendance.shiftsPage.countEarly',
  count_overtime: 'attendance.shiftsPage.countOvertime',
}

/** What a version changes compared with the one before it, as short lines. */
function useChanges() {
  const { t } = useTranslation()
  const weekday = useWeekdayName()
  const shiftName = useShiftName()
  return (v: ScheduleVersion, before: ScheduleVersion): string[] => {
    const lines: string[] = []
    if (v.weekdays.join() !== before.weekdays.join()) {
      lines.push(t('attendance.scheduling.upcoming.weekdays', { days: v.weekdays.map(weekday).join(', ') }))
    }
    for (const s of v.shifts) {
      const old = before.shifts.find((x) => x.code === s.code)
      if (!old || old.start_time !== s.start_time || old.end_time !== s.end_time) {
        lines.push(`${shiftName(s.code)} ${s.start_time}–${s.end_time}`)
      }
    }
    for (const key of Object.keys(RULE_LABELS) as (keyof AttendanceRules)[]) {
      if (v[key] !== before[key]) {
        const value = typeof v[key] === 'boolean' ? (v[key] ? t('common.yes') : t('common.no')) : String(v[key])
        lines.push(`${t(RULE_LABELS[key])}: ${value}`)
      }
    }
    return lines.length ? lines : [t('attendance.scheduling.upcoming.noChange')]
  }
}

/** Upcoming changes per workplace (date, what changes), each deletable. */
export function UpcomingCard({ scheduling, canEdit }: { scheduling: Scheduling; canEdit: boolean }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const formatDay = useDayName()
  const changes = useChanges()
  const [deleting, setDeleting] = useState<{ version: ScheduleVersion; workplace: string } | null>(null)
  const remove = useMutation({
    mutationFn: async (id: string) => api.delete(`/attendance/scheduling/versions/${id}`),
    onSuccess: () => {
      invalidateScheduling(queryClient)
      setDeleting(null)
    },
  })
  const withUpcoming = scheduling.workplaces.filter((w) => w.upcoming.length)

  return (
    <Card title={t('attendance.scheduling.upcoming.title')}>
      {withUpcoming.length === 0 ? (
        <p className="text-sm text-stone-500">{t('attendance.scheduling.upcoming.none')}</p>
      ) : (
        <div className="space-y-4">
          {withUpcoming.map((w) => (
            <section key={w.id}>
              {scheduling.workplaces.length > 1 && <h3 className="text-sm font-semibold text-stone-900">{w.name}</h3>}
              <ul className="divide-y divide-stone-100">
                {w.upcoming.map((v, i) => (
                  <li key={v.id} className="flex flex-wrap items-start justify-between gap-2 py-2">
                    <div className="min-w-0">
                      <p className="font-medium text-stone-900">
                        {t('attendance.scheduling.upcoming.from', { date: formatDay(v.effective_from) })}
                      </p>
                      <ul className="text-xs text-stone-600">
                        {changes(v, i === 0 ? w.current : w.upcoming[i - 1]).map((line) => (
                          <li key={line}>{line}</li>
                        ))}
                      </ul>
                    </div>
                    {canEdit && (
                      <Button
                        variant="ghost"
                        className="px-2 py-1 text-xs text-red-700"
                        onClick={() => setDeleting({ version: v, workplace: w.name })}
                      >
                        {t('attendance.scheduling.delete')}
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
      {deleting && (
        <ConfirmDialog
          open
          tone="danger"
          title={t('attendance.scheduling.upcoming.deleteTitle')}
          body={t('attendance.scheduling.upcoming.deleteConfirm', {
            date: formatDay(deleting.version.effective_from),
            name: deleting.workplace,
          })}
          confirmLabel={t('attendance.scheduling.delete')}
          loading={remove.isPending}
          error={remove.isError ? errorMessage(remove.error) : null}
          onConfirm={() => remove.mutate(deleting.version.id)}
          onClose={() => {
            setDeleting(null)
            remove.reset()
          }}
        />
      )}
    </Card>
  )
}
