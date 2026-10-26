import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ActionMenu } from '@/components/ActionMenu'
import { Icon } from '@/components/icons'
import { Button, Card, ConfirmDialog, cx, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useCalendarNames, useLocalized } from '@/lib/format'
import type { CalendarDay, Holiday, HolidayCopyResult } from '@/lib/types'
import { invalidateScheduling, useAttendanceCalendar } from '../api'
import { isoWeekday, useDayName, useWeekdayName, WEEKDAYS } from './shared'

interface CalendarCardProps {
  workplaceId: string
  /** YYYY-MM */
  month: string
  today: string
  onMonth(month: string): void
  /** The year's holidays (this workplace's are listed under the grid). */
  holidays: Holiday[]
  /** With attendance.scheduling: a tapped day opens the Holiday sheet. */
  canEdit: boolean
  onDay(date: string, day: CalendarDay): void
  onHoliday(holiday: Holiday): void
  onDeleteHoliday(holiday: Holiday): void
  /** **Add holiday** in the card header (today, or the shown month's 1st). */
  onAddHoliday(): void
  /** The result line of **Copy holidays from {last year}** (the ⋮ menu). */
  onDone(message: string): void
}

function shiftMonth(month: string, by: number): string {
  const y = Number(month.slice(0, 4))
  const m = Number(month.slice(5, 7)) - 1 + by
  const d = new Date(Date.UTC(y, m, 1))
  return d.toISOString().slice(0, 7)
}

/**
 * One workplace's month, Monday first: the day number, holiday names (a dot on phones, the list
 * below names them), untracked weekdays greyed "Day off", today outlined. The month's holidays are listed under it. With
 * attendance.scheduling the header has **Add holiday** and a ⋮ menu with **Copy holidays from
 * {last year}** (into the shown month's year; same month / day, Khmer holidays then adjusted).
 */
export function CalendarCard(props: CalendarCardProps) {
  const { workplaceId, month, today, onMonth, holidays, canEdit, onDay, onHoliday, onDeleteHoliday, onAddHoliday, onDone } = props
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const [copying, setCopying] = useState(false)
  const names = useCalendarNames()
  const weekday = useWeekdayName()
  const localized = useLocalized()
  const formatDay = useDayName()
  const year = Number(month.slice(0, 4))
  const m = Number(month.slice(5, 7))
  const calendar = useAttendanceCalendar(year, m, [workplaceId])
  const copy = useMutation({
    mutationFn: async () =>
      (await api.post<HolidayCopyResult>('/attendance/holidays/copy', { from_year: year - 1, to_year: year })).data,
    onSuccess: (result) => {
      invalidateScheduling(queryClient)
      setCopying(false)
      const parts = [t('attendance.scheduling.copy.done', { count: result.created.length })]
      if (result.skipped) parts.push(t('attendance.scheduling.copy.skipped', { count: result.skipped }))
      if (result.records_removed) parts.push(t('attendance.scheduling.recordsRemoved', { count: result.records_removed }))
      if (result.skipped_locked) parts.push(t('attendance.scheduling.skippedLocked', { count: result.skipped_locked }))
      onDone(parts.join(' '))
    },
  })
  const days = calendar.data?.year === year && calendar.data.month === m ? calendar.data.days : []
  const lead = days.length ? isoWeekday(days[0].date) - 1 : 0
  const first = `${month}-01`
  const last = days.length ? days[days.length - 1].date : first
  const monthHolidays = holidays.filter(
    (h) =>
      h.start_date <= last &&
      h.end_date >= first &&
      (h.scope === 'all' || h.workplaces.some((w) => w.id === workplaceId)),
  )
  const range = (h: Holiday) =>
    h.start_date === h.end_date ? formatDay(h.start_date) : `${formatDay(h.start_date)} – ${formatDay(h.end_date)}`

  return (
    <Card
      title={t('attendance.scheduling.calendar')}
      actions={
        canEdit && (
          <div className="flex items-center gap-1">
            <Button className="px-3 py-1.5" onClick={onAddHoliday}>
              <Icon name="plus" width={16} height={16} />
              {t('attendance.scheduling.holiday.add')}
            </Button>
            <ActionMenu
              label={t('attendance.scheduling.holidayActions')}
              items={[
                {
                  key: 'copy',
                  label: t('attendance.scheduling.copy.button', { year: year - 1 }),
                  onSelect: () => setCopying(true),
                },
              ]}
            />
          </div>
        )
      }
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <Button variant="ghost" className="px-2" aria-label={t('common.previous')} onClick={() => onMonth(shiftMonth(month, -1))}>
            <Icon name="chevronLeft" />
          </Button>
          <span className="min-w-[8.5rem] text-center text-sm font-semibold text-stone-900">{names.monthYear(month)}</span>
          <Button variant="ghost" className="px-2" aria-label={t('common.next')} onClick={() => onMonth(shiftMonth(month, 1))}>
            <Icon name="chevronRight" />
          </Button>
        </div>
        <Button
          variant="secondary"
          className="px-3 py-1.5"
          disabled={month === today.slice(0, 7)}
          onClick={() => onMonth(today.slice(0, 7))}
        >
          {t('attendance.scheduling.today')}
        </Button>
      </div>
      <div className="relative">
        <div className="grid grid-cols-7 gap-1 text-center text-xs font-semibold text-stone-600">
          {WEEKDAYS.map((d) => (
            <div key={d} className="py-1">
              {weekday(d)}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-1">
          {Array.from({ length: lead }, (_, i) => (
            <div key={`lead-${i}`} />
          ))}
          {days.map((d) => (
            <DayCell key={d.date} day={d} today={today} canEdit={canEdit} onClick={() => onDay(d.date, d)} />
          ))}
        </div>
        {calendar.isFetching && !days.length && (
          <div className="flex justify-center py-16 text-brand-600">
            <Spinner />
          </div>
        )}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-stone-700" aria-label={t('attendance.scheduling.legend')}>
        <li className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-sm bg-amber-200 ring-1 ring-amber-500" aria-hidden />
          {t('attendance.scheduling.legendHoliday')}
        </li>
        <li className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-sm bg-stone-200 ring-1 ring-stone-400" aria-hidden />
          {t('attendance.scheduling.legendDayOff')}
        </li>
        <li className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-sm bg-white ring-1 ring-stone-400" aria-hidden />
          {t('attendance.scheduling.legendTracked')}
        </li>
      </ul>

      <h3 className="mt-5 text-sm font-semibold text-stone-900">
        {t('attendance.scheduling.monthHolidays', { month: names.monthYear(month) })}
      </h3>
      {monthHolidays.length === 0 ? (
        <p className="mt-1 text-sm text-stone-500">{t('attendance.scheduling.noHolidays')}</p>
      ) : (
        <ul className="mt-1 divide-y divide-stone-100">
          {monthHolidays.map((h) => (
            <HolidayRow
              key={h.id}
              holiday={h}
              range={range(h)}
              name={localized(h)}
              canEdit={canEdit}
              onEdit={() => onHoliday(h)}
              onDelete={() => onDeleteHoliday(h)}
            />
          ))}
        </ul>
      )}
      {copying && (
        <ConfirmDialog
          open
          title={t('attendance.scheduling.copy.button', { year: year - 1 })}
          body={t('attendance.scheduling.copy.confirm', { from: year - 1, to: year })}
          confirmLabel={t('attendance.scheduling.copy.confirmButton')}
          loading={copy.isPending}
          error={copy.isError ? errorMessage(copy.error) : null}
          onConfirm={() => copy.mutate()}
          onClose={() => {
            setCopying(false)
            copy.reset()
          }}
        />
      )}
    </Card>
  )
}

function DayCell({
  day,
  today,
  canEdit,
  onClick,
}: {
  day: CalendarDay
  today: string
  canEdit: boolean
  onClick(): void
}) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const formatDay = useDayName()
  const holidayNames = day.holidays.map((h) => localized(h))
  const holiday = day.status === 'off' && day.day_off?.reason === 'holiday'
  const weekdayOff = day.status === 'off' && !holiday
  const label = [
    formatDay(day.date),
    ...holidayNames,
    weekdayOff ? t('attendance.scheduling.dayOff') : null,
  ]
    .filter(Boolean)
    .join(' · ')
  const content = (
    <>
      <span className={cx('text-sm font-semibold tabular-nums', day.date === today && 'text-stone-950')}>
        {Number(day.date.slice(8, 10))}
      </span>
      {/* Phones: a dot; the list under the grid names the holidays. */}
      {holidayNames.length > 0 && <span className="mx-auto mt-0.5 h-1.5 w-1.5 rounded-full bg-amber-600 sm:hidden" aria-hidden />}
      <span className="hidden min-w-0 sm:block">
        {holidayNames.map((n) => (
          <span key={n} className="block truncate text-[11px] font-medium leading-tight text-amber-900" title={n}>
            {n}
          </span>
        ))}
        {weekdayOff && <span className="block truncate text-[11px] text-stone-600">{t('attendance.scheduling.dayOff')}</span>}
        {!!day.working && (
          <span className="block truncate text-[11px] font-medium text-brand-700">
            {t('attendance.holidayWork.working', { count: day.working })}
          </span>
        )}
      </span>
    </>
  )
  const className = cx(
    'flex min-h-[44px] min-w-0 flex-col items-stretch rounded-md p-1 text-left sm:min-h-[72px] sm:p-1.5',
    holiday && 'bg-amber-100 text-amber-950 ring-1 ring-inset ring-amber-400',
    weekdayOff && 'bg-stone-200 text-stone-600',
    day.status === 'tracked' && 'bg-white text-stone-900 ring-1 ring-inset ring-stone-200',
    day.date === today && 'outline outline-2 outline-offset-1 outline-stone-900',
  )
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      disabled={!canEdit && holidayNames.length === 0}
      className={cx(className, canEdit && 'hover:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500')}
    >
      {content}
    </button>
  )
}

export function HolidayRow({
  holiday: h,
  range,
  name,
  canEdit,
  onEdit,
  onDelete,
}: {
  holiday: Holiday
  range: string
  name: string
  canEdit: boolean
  onEdit(): void
  onDelete(): void
}) {
  const { t } = useTranslation()
  return (
    <li className="flex flex-wrap items-start justify-between gap-2 py-2">
      <div className="min-w-0">
        <p className="font-medium text-stone-900">{name}</p>
        <p className="text-xs text-stone-600">
          {range}
          {h.days > 1 && ` · ${t('attendance.scheduling.days', { count: h.days })}`}
          {' · '}
          {h.scope === 'all' ? t('attendance.scheduling.allWorkplaces') : h.workplaces.map((w) => w.name).join(', ')}
        </p>
        {h.note && <p className="mt-0.5 text-xs text-stone-500">{h.note}</p>}
      </div>
      {canEdit && (
        <div className="flex gap-1">
          <Button variant="ghost" className="px-2 py-1 text-xs" onClick={onEdit}>
            <Icon name="pencil" width={14} height={14} />
            {t('common.edit')}
          </Button>
          <Button variant="ghost" className="px-2 py-1 text-xs text-red-700" onClick={onDelete}>
            {t('attendance.scheduling.delete')}
          </Button>
        </div>
      )}
    </li>
  )
}
