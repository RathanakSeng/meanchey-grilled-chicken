import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Sheet } from '@/components/Sheet'
import { Alert, Button, ConfirmDialog, Spinner, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useLocalized } from '@/lib/format'
import type {
  AttendanceRules,
  EmployeeScheduleInput,
  EmployeeScheduleRow,
  EmployeeScheduleWriteResult,
  OverrideVersion,
  ShiftCode,
  ShiftTime,
} from '@/lib/types'
import { invalidateScheduling, useEmployeeSchedule, useScheduling } from '../api'
import { AppliesFrom, TimeInput, WEEKDAYS, useDayName, useWeekdayName, useWeekdaysText, windowsOf } from './shared'

const CODES: ShiftCode[] = ['morning', 'afternoon']
const FALLBACK_TIMES: Record<ShiftCode, ShiftTime> = {
  morning: { start_time: '07:00', end_time: '12:00' },
  afternoon: { start_time: '13:00', end_time: '15:00' },
}

/** keep: leave as it is (several employees); workplace: inherit; custom: their own value. */
type Mode = 'keep' | 'workplace' | 'custom'

interface Inherited {
  weekdays: number[]
  times: Record<ShiftCode, ShiftTime>
  rules: AttendanceRules
}

function timesOf(shifts: (ShiftTime & { code: ShiftCode })[], base = FALLBACK_TIMES): Record<ShiftCode, ShiftTime> {
  const out = { ...base }
  for (const s of shifts) out[s.code] = { start_time: s.start_time, end_time: s.end_time }
  return out
}

/**
 * Edit the schedule of one or several employees. Three sections, each with a Workplace / Custom
 * switch (several employees: also "No change"; Workplace shows the inherited value greyed):
 * working days, shifts (at least one) and shift times with their derived windows. "Applies from"
 * (today by default, never the past). One employee: the week's preview, upcoming changes with
 * delete, and Reset to workplace.
 */
export function EmployeeScheduleSheet({
  rows,
  today,
  onClose,
  onDone,
}: {
  rows: EmployeeScheduleRow[]
  today: string
  onClose(): void
  onDone(message: string): void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const single = rows.length === 1 ? rows[0] : null
  const [from, setFrom] = useState(today)
  const detail = useEmployeeSchedule(single?.user.id ?? null, from)
  const scheduling = useScheduling([])
  const workplaceIds = [...new Set(rows.map((r) => r.workplace?.id ?? ''))]
  const shared = workplaceIds.length === 1 ? scheduling.data?.workplaces.find((w) => w.id === workplaceIds[0]) : undefined
  const inherited: Inherited | null =
    single && detail.data
      ? {
          weekdays: detail.data.workplace_schedule.weekdays,
          times: timesOf(detail.data.workplace_schedule.shifts),
          rules: detail.data.rules,
        }
      : shared
        ? { weekdays: shared.current.weekdays, times: timesOf(shared.current.shifts), rules: shared.current }
        : null

  const [ready, setReady] = useState(!single)
  const [days, setDays] = useState<{ mode: Mode; value: number[] }>({ mode: 'keep', value: [...WEEKDAYS] })
  const [codes, setCodes] = useState<{ mode: Mode; value: ShiftCode[] }>({ mode: 'keep', value: [...CODES] })
  const [times, setTimes] = useState<{ mode: Mode; value: Record<ShiftCode, ShiftTime> }>({
    mode: 'keep',
    value: { ...FALLBACK_TIMES },
  })
  const [confirm, setConfirm] = useState<'reset' | OverrideVersion | null>(null)

  // One employee: start from their schedule today (custom where their override sets it).
  useEffect(() => {
    if (!single || ready || !detail.data) return
    const d = detail.data
    const current = d.current
    setDays({ mode: current?.weekdays ? 'custom' : 'workplace', value: d.schedule.weekdays })
    setCodes({ mode: current?.shift_codes ? 'custom' : 'workplace', value: d.schedule.shifts.map((s) => s.code) })
    setTimes({
      mode: current?.shift_times ? 'custom' : 'workplace',
      value: timesOf(d.schedule.shifts, timesOf(d.workplace_schedule.shifts)),
    })
    setReady(true)
  }, [single, ready, detail.data])

  // Before anything is chosen for several employees, start the values from their workplace.
  useEffect(() => {
    if (single || !inherited) return
    setDays((s) => (s.mode === 'keep' ? { ...s, value: inherited.weekdays } : s))
    setTimes((s) => (s.mode === 'keep' ? { ...s, value: inherited.times } : s))
  }, [single, shared?.id])

  const save = useMutation({
    mutationFn: async (body: EmployeeScheduleInput) =>
      (await api.put<EmployeeScheduleWriteResult>('/attendance/scheduling/employees', body)).data,
    onSuccess: (result) => {
      invalidateScheduling(queryClient)
      onDone(
        result.changed.length
          ? t('attendance.employeeSchedules.saved', { count: result.changed.length })
          : t('attendance.employeeSchedules.unchanged'),
      )
    },
  })
  const reset = useMutation({
    mutationFn: async () =>
      (
        await api.post<EmployeeScheduleWriteResult>('/attendance/scheduling/employees/reset', {
          user_ids: rows.map((r) => r.user.id!),
          effective_from: from,
        })
      ).data,
    onSuccess: (result) => {
      invalidateScheduling(queryClient)
      onDone(t('attendance.employeeSchedules.resetDone', { count: result.changed.length }))
    },
  })
  const removeVersion = useMutation({
    mutationFn: async (v: OverrideVersion) =>
      api.delete(`/attendance/scheduling/employees/${single!.user.id}/versions/${v.id}`),
    onSuccess: () => {
      invalidateScheduling(queryClient)
      setConfirm(null)
    },
  })

  const shownCodes = codes.mode === 'custom' ? codes.value : CODES
  const invalidTimes = times.mode === 'custom' && shownCodes.some((c) => times.value[c].start_time >= times.value[c].end_time)
  const nothing = days.mode === 'keep' && codes.mode === 'keep' && times.mode === 'keep'
  const valid =
    !nothing &&
    (days.mode !== 'custom' || days.value.length > 0) &&
    (codes.mode !== 'custom' || codes.value.length > 0) &&
    !invalidTimes

  const body = (): EmployeeScheduleInput => {
    const out: EmployeeScheduleInput = { user_ids: rows.map((r) => r.user.id!), effective_from: from }
    if (days.mode !== 'keep') out.weekdays = days.mode === 'custom' ? days.value : 'inherit'
    if (codes.mode !== 'keep') out.shift_codes = codes.mode === 'custom' ? codes.value : 'inherit'
    if (times.mode !== 'keep') {
      out.shift_times =
        times.mode === 'custom' ? Object.fromEntries(shownCodes.map((c) => [c, times.value[c]])) : 'inherit'
    }
    return out
  }
  const busy = save.isPending || reset.isPending || removeVersion.isPending
  const title = single
    ? t('attendance.employeeSchedules.editOne', { name: single.user.full_name })
    : t('attendance.employeeSchedules.editSeveral', { count: rows.length })

  return (
    <Sheet
      open
      busy={busy}
      title={title}
      onClose={onClose}
      footer={
        <div className="flex flex-wrap items-center justify-between gap-2">
          {single?.summary.custom.length || detail.data?.upcoming.length ? (
            <Button variant="ghost" className="text-red-700" disabled={busy} onClick={() => setConfirm('reset')}>
              {t('attendance.employeeSchedules.reset')}
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button variant="secondary" disabled={busy} onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button loading={save.isPending} disabled={!valid || !ready} onClick={() => save.mutate(body())}>
              {t('common.save')}
            </Button>
          </div>
        </div>
      }
    >
      {!ready ? (
        <div className="flex justify-center py-16 text-brand-600">
          <Spinner />
        </div>
      ) : (
        <div className="space-y-5">
          {!single && !shared && (
            <Alert>{t('attendance.employeeSchedules.severalWorkplaces')}</Alert>
          )}
          <Section
            title={t('attendance.employeeSchedules.workingDays')}
            mode={days.mode}
            several={!single}
            onMode={(mode) => setDays((s) => ({ ...s, mode }))}
          >
            <WeekdayToggles
              value={days.mode === 'workplace' && inherited ? inherited.weekdays : days.value}
              disabled={days.mode !== 'custom'}
              onChange={(value) => setDays({ mode: 'custom', value })}
            />
            {days.mode === 'custom' && days.value.length === 0 && (
              <p className="text-sm text-red-700">{t('attendance.employeeSchedules.atLeastOneDay')}</p>
            )}
          </Section>

          <Section
            title={t('attendance.employeeSchedules.shifts')}
            mode={codes.mode}
            several={!single}
            onMode={(mode) => setCodes((s) => ({ ...s, mode }))}
          >
            <div className="flex flex-wrap gap-4">
              {CODES.map((code) => {
                const on = codes.mode === 'custom' ? codes.value.includes(code) : true
                return (
                  <label
                    key={code}
                    className={cx(
                      'flex select-none items-center gap-2 text-sm',
                      codes.mode === 'custom' ? 'cursor-pointer text-stone-800' : 'text-stone-400',
                    )}
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 rounded border-stone-300 accent-brand-600"
                      checked={on}
                      disabled={codes.mode !== 'custom'}
                      onChange={(e) =>
                        setCodes({
                          mode: 'custom',
                          value: CODES.filter((c) => (c === code ? e.target.checked : codes.value.includes(c))),
                        })
                      }
                    />
                    {t(`attendance.shiftsShort.${code}`)}
                  </label>
                )
              })}
            </div>
            {codes.mode === 'custom' && codes.value.length === 0 && (
              <p className="text-sm text-red-700">{t('attendance.employeeSchedules.atLeastOneShift')}</p>
            )}
          </Section>

          <Section
            title={t('attendance.employeeSchedules.shiftTimes')}
            mode={times.mode}
            several={!single}
            onMode={(mode) => setTimes((s) => ({ ...s, mode }))}
          >
            <div className="space-y-3">
              {shownCodes.map((code) => {
                const value = times.mode === 'workplace' && inherited ? inherited.times[code] : times.value[code]
                const editable = times.mode === 'custom'
                const set = (patch: Partial<ShiftTime>) =>
                  setTimes((s) => ({ mode: 'custom', value: { ...s.value, [code]: { ...s.value[code], ...patch } } }))
                const w = inherited ? windowsOf(value.start_time, value.end_time, inherited.rules) : null
                return (
                  <div key={code} className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="w-full text-sm font-medium text-stone-800 sm:w-24">{t(`attendance.shiftsShort.${code}`)}</span>
                      <TimeInput
                        value={value.start_time}
                        disabled={!editable}
                        aria-label={t('attendance.employeeSchedules.start')}
                        onChange={(e) => e.target.value && set({ start_time: e.target.value })}
                      />
                      <span className="text-stone-400">–</span>
                      <TimeInput
                        value={value.end_time}
                        disabled={!editable}
                        aria-label={t('attendance.employeeSchedules.end')}
                        onChange={(e) => e.target.value && set({ end_time: e.target.value })}
                      />
                    </div>
                    {w && value.start_time < value.end_time && (
                      <p className="text-xs tabular-nums text-stone-500">
                        {t('attendance.employeeSchedules.windows', {
                          opens: w.check_in_opens,
                          late: value.start_time,
                          absent: w.absent_from,
                          out: w.check_out_opens,
                          outUntil: w.check_out_until,
                        })}
                      </p>
                    )}
                  </div>
                )
              })}
              {invalidTimes && <p className="text-sm text-red-700">{t('attendance.employeeSchedules.endAfterStart')}</p>}
            </div>
          </Section>

          <div className="space-y-1">
            <AppliesFrom value={from} min={today} onChange={setFrom} disabled={busy} />
            {from === today && <p className="text-xs text-stone-500">{t('attendance.employeeSchedules.todayNote')}</p>}
          </div>

          {save.isError && <Alert tone="error">{errorMessage(save.error)}</Alert>}

          {single && detail.data && (
            <>
              <WeekPreview preview={detail.data.preview} />
              <Upcoming versions={detail.data.upcoming} onDelete={(v) => setConfirm(v)} />
            </>
          )}
        </div>
      )}

      {confirm === 'reset' && (
        <ConfirmDialog
          open
          title={t('attendance.employeeSchedules.resetTitle')}
          body={t('attendance.employeeSchedules.resetBody', { count: rows.length })}
          confirmLabel={t('attendance.employeeSchedules.reset')}
          loading={reset.isPending}
          error={reset.isError ? errorMessage(reset.error) : null}
          onConfirm={() => reset.mutate()}
          onClose={() => {
            setConfirm(null)
            reset.reset()
          }}
        />
      )}
      {confirm && confirm !== 'reset' && (
        <ConfirmDialog
          open
          tone="danger"
          title={t('attendance.scheduling.upcoming.deleteTitle')}
          body={t('attendance.employeeSchedules.deleteVersion', { date: confirm.effective_from })}
          confirmLabel={t('attendance.scheduling.delete')}
          loading={removeVersion.isPending}
          error={removeVersion.isError ? errorMessage(removeVersion.error) : null}
          onConfirm={() => removeVersion.mutate(confirm)}
          onClose={() => {
            setConfirm(null)
            removeVersion.reset()
          }}
        />
      )}
    </Sheet>
  )
}

function Section({
  title,
  mode,
  several,
  onMode,
  children,
}: {
  title: string
  mode: Mode
  several: boolean
  onMode(mode: Mode): void
  children: ReactNode
}) {
  const { t } = useTranslation()
  const modes: Mode[] = several ? ['keep', 'workplace', 'custom'] : ['workplace', 'custom']
  return (
    <section className="space-y-2 rounded-xl p-3 ring-1 ring-stone-200">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-stone-900">{title}</h3>
        <div role="radiogroup" aria-label={title} className="inline-flex gap-1 rounded-full bg-stone-100 p-1">
          {modes.map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              onClick={() => onMode(m)}
              className={cx(
                'rounded-full px-3 py-1 text-xs font-medium transition',
                mode === m ? 'bg-white text-stone-900 shadow-sm ring-1 ring-stone-200' : 'text-stone-600 hover:text-stone-900',
              )}
            >
              {t(`attendance.employeeSchedules.mode.${m}`)}
            </button>
          ))}
        </div>
      </div>
      <div className={cx(mode !== 'custom' && 'opacity-60')}>{children}</div>
    </section>
  )
}

function WeekdayToggles({
  value,
  disabled,
  onChange,
}: {
  value: number[]
  disabled: boolean
  onChange(value: number[]): void
}) {
  const weekday = useWeekdayName()
  return (
    <div className="grid grid-cols-7 gap-1">
      {WEEKDAYS.map((d) => {
        const on = value.includes(d)
        return (
          <button
            key={d}
            type="button"
            aria-pressed={on}
            disabled={disabled}
            onClick={() => onChange(on ? value.filter((x) => x !== d) : [...value, d].sort())}
            className={cx(
              'min-h-10 rounded-lg px-1 text-xs font-medium ring-1 ring-inset transition',
              on ? 'bg-brand-600 text-white ring-brand-600' : 'bg-white text-stone-700 ring-stone-300',
              disabled ? 'cursor-default' : 'hover:ring-brand-400',
            )}
          >
            {weekday(d)}
          </button>
        )
      })}
    </div>
  )
}

function WeekPreview({ preview }: { preview: NonNullable<ReturnType<typeof useEmployeeSchedule>['data']>['preview'] }) {
  const { t } = useTranslation()
  const dayName = useDayName()
  const localized = useLocalized()
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold text-stone-900">{t('attendance.employeeSchedules.thisWeek')}</h3>
      <ul className="divide-y divide-stone-100 rounded-xl ring-1 ring-stone-200">
        {preview.map((d) => (
          <li key={d.date} className="flex flex-wrap items-baseline justify-between gap-2 px-3 py-2 text-sm">
            <span className="text-stone-700">{dayName(d.date)}</span>
            <span className="text-right tabular-nums">
              {d.day_off ? (
                <span className="text-stone-400">
                  {d.day_off.reason === 'holiday' && d.day_off.holidays.length
                    ? t('attendance.dayOff.holiday', { name: d.day_off.holidays.map((h) => localized(h)).join(', ') })
                    : t('attendance.dayOff.weekday')}
                </span>
              ) : (
                <>
                  {d.works_on_holiday && (
                    <span className="mr-2 text-xs font-medium text-amber-800">
                      {t('attendance.employeeSchedules.worksOnHoliday', { name: localized(d.works_on_holiday) })}
                    </span>
                  )}
                  <span className="text-stone-800">
                    {d.shifts.length
                      ? d.shifts.map((s) => `${t(`attendance.shiftsShort.${s.code}`)} ${s.start_time}–${s.end_time}`).join(', ')
                      : '—'}
                  </span>
                </>
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Upcoming({ versions, onDelete }: { versions: OverrideVersion[]; onDelete(v: OverrideVersion): void }) {
  const { t } = useTranslation()
  const dayName = useDayName()
  const weekdaysText = useWeekdaysText()
  const describe = (v: OverrideVersion) => {
    const parts = [
      v.weekdays && weekdaysText(v.weekdays),
      v.shift_codes && v.shift_codes.map((c) => t(`attendance.shiftsShort.${c}`)).join(', '),
      v.shift_times &&
        Object.entries(v.shift_times)
          .map(([c, s]) => `${t(`attendance.shiftsShort.${c}`)} ${s!.start_time}–${s!.end_time}`)
          .join(', '),
    ].filter(Boolean)
    return parts.length ? parts.join(' · ') : t('attendance.employeeSchedules.backToWorkplace')
  }
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold text-stone-900">{t('attendance.scheduling.upcoming.title')}</h3>
      {versions.length === 0 ? (
        <p className="text-sm text-stone-500">{t('attendance.scheduling.upcoming.none')}</p>
      ) : (
        <ul className="divide-y divide-stone-100 rounded-xl ring-1 ring-stone-200">
          {versions.map((v) => (
            <li key={v.id} className="flex items-start justify-between gap-2 px-3 py-2 text-sm">
              <span className="min-w-0">
                <span className="block font-medium text-stone-800">
                  {t('attendance.scheduling.upcoming.from', { date: dayName(v.effective_from) })}
                </span>
                <span className="block text-stone-600">{describe(v)}</span>
              </span>
              <Button variant="ghost" className="text-red-700" onClick={() => onDelete(v)}>
                {t('attendance.scheduling.delete')}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
