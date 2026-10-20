import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams, useSearchParams } from 'react-router-dom'
import { usePermission } from '@/auth/usePermission'
import { Alert, PageHeader, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { paths } from '@/lib/paths'
import type { CalendarDay, Holiday, HolidayWriteResult } from '@/lib/types'
import { businessToday, invalidateScheduling, useHolidays, useScheduling } from '../api'
import { CalendarCard } from './CalendarCard'
import { DeleteHolidayDialog, HolidaySheet } from './HolidaySheet'
import { ShiftsCard } from './ShiftsCard'
import { UpcomingCard } from './UpcomingCard'
import { WeekdaysCard } from './WeekdaysCard'

/**
 * Attendance → Scheduling → one workplace (`/attendance/scheduling/:workplaceId`, `?m=` the
 * calendar month): its calendar and holidays, tracked weekdays, shift schedule and rules and
 * upcoming changes. Every save is for this workplace; "Apply to all workplaces" next to Save
 * sends it to every workplace instead. Viewing needs attendance.view or attendance.scheduling;
 * the edit controls need attendance.scheduling.
 */
export function SchedulingPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const canEdit = usePermission('attendance.scheduling')
  const { workplaceId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const today = businessToday()
  const month = /^\d{4}-\d{2}$/.test(params.get('m') ?? '') ? params.get('m')! : today.slice(0, 7)
  const scheduling = useScheduling([workplaceId])
  const monthHolidays = useHolidays(Number(month.slice(0, 4)))
  const [notice, setNotice] = useState<string | null>(null)
  const [sheet, setSheet] = useState<{ holiday: Holiday | null; date: string } | null>(null)
  const [deleting, setDeleting] = useState<Holiday | null>(null)

  const setMonth = (m: string) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p)
        if (m === today.slice(0, 7)) next.delete('m')
        else next.set('m', m)
        return next
      },
      { replace: true },
    )

  const remove = useMutation({
    mutationFn: async (h: Holiday) => (await api.delete<HolidayWriteResult>(`/attendance/holidays/${h.id}`)).data,
    onSuccess: (result) => {
      invalidateScheduling(queryClient)
      setDeleting(null)
      const parts = [t('attendance.scheduling.holiday.deleted')]
      if (result.absents_recreated) parts.push(t('attendance.scheduling.absentsRecreated', { count: result.absents_recreated }))
      setNotice(parts.join(' '))
    },
  })

  const openDay = (date: string, day: CalendarDay) => {
    if (!canEdit) return
    const existing = day.holidays.length
      ? (monthHolidays.data ?? []).find((h) => h.id === day.holidays[0].id)
      : undefined
    setSheet({ holiday: existing ?? null, date })
  }

  // The previous workplace's data stays while another loads: only use this one's.
  const data = scheduling.data?.workplaces[0]?.id === workplaceId ? scheduling.data : undefined
  const workplace = data?.workplaces[0]
  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <PageHeader
        title={workplace?.name ?? t('attendance.scheduling.title')}
        subtitle={t('attendance.scheduling.title')}
        back={paths.attendanceScheduling}
      />

      {notice && (
        <Alert tone="success">
          <div className="flex items-start justify-between gap-2">
            <span>{notice}</span>
            <button type="button" className="text-xs font-medium underline" onClick={() => setNotice(null)}>
              {t('common.close')}
            </button>
          </div>
        </Alert>
      )}
      {scheduling.isError && <Alert tone="error">{errorMessage(scheduling.error)}</Alert>}
      {!data || !workplace ? (
        !scheduling.isError && (
          <div className="flex justify-center py-16 text-brand-600">
            <Spinner />
          </div>
        )
      ) : (
        <>
          <CalendarCard
            workplaceId={workplace.id}
            month={month}
            today={data.today}
            onMonth={setMonth}
            holidays={monthHolidays.data ?? []}
            canEdit={canEdit}
            onDay={openDay}
            onHoliday={(h) => setSheet({ holiday: h, date: h.start_date })}
            onDeleteHoliday={setDeleting}
            onAddHoliday={() =>
              setSheet({ holiday: null, date: month === data.today.slice(0, 7) ? data.today : `${month}-01` })
            }
            onDone={setNotice}
          />
          <WeekdaysCard scheduling={data} canEdit={canEdit} onDone={setNotice} />
          <ShiftsCard scheduling={data} canEdit={canEdit} onDone={setNotice} />
          <UpcomingCard scheduling={data} canEdit={canEdit} />
        </>
      )}

      {sheet && data && workplace && (
        <HolidaySheet
          key={sheet.holiday?.id ?? sheet.date}
          holiday={sheet.holiday}
          date={sheet.date}
          today={data.today}
          workplace={workplace}
          workplaceOptions={data.workplace_options}
          onClose={() => setSheet(null)}
          onDone={(message) => {
            setSheet(null)
            setNotice(message)
          }}
        />
      )}
      {deleting && data && (
        <DeleteHolidayDialog
          holiday={deleting}
          today={data.today}
          loading={remove.isPending}
          error={remove.isError ? errorMessage(remove.error) : null}
          onConfirm={() => remove.mutate(deleting)}
          onClose={() => {
            setDeleting(null)
            remove.reset()
          }}
        />
      )}
    </div>
  )
}
