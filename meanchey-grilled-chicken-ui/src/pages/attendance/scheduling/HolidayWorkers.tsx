import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Alert, Button, ConfirmDialog, Spinner, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import type {
  Holiday,
  HolidayException,
  HolidayExceptionInput,
  HolidayExceptionWriteResult,
  ShiftCode,
  ShiftTime,
} from '@/lib/types'
import { invalidateScheduling, useEmployeeSchedules, useHolidayExceptions } from '../api'
import { addDays, TimeInput, useDayName } from './shared'

const CODES: ShiftCode[] = ['morning', 'afternoon']

/** The holiday's days from today on. */
function workDays(holiday: Holiday, today: string): string[] {
  const out: string[] = []
  for (let d = holiday.start_date; d <= holiday.end_date; d = addDays(d, 1)) if (d >= today) out.push(d)
  return out
}

/**
 * ធ្វើការថ្ងៃឈប់សម្រាក / Who works on this holiday (attendance.scheduling): employees in scope set
 * to work on days of the holiday (today or later), with their normal shifts or chosen ones and
 * optional times; the list with Remove. Removing today's asks first: what they recorded today is
 * removed (corrected records are kept).
 */
export function HolidayWorkers({ holiday, today }: { holiday: Holiday; today: string }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const dayName = useDayName()
  const exceptions = useHolidayExceptions(holiday.id)
  const employees = useEmployeeSchedules({ workplaceIds: [], customOnly: false, q: '' })
  const days = workDays(holiday, today)
  const [adding, setAdding] = useState(false)
  const [users, setUsers] = useState<string[]>([])
  const [dates, setDates] = useState<string[]>(days)
  const [ownShifts, setOwnShifts] = useState(false)
  const [codes, setCodes] = useState<ShiftCode[]>([...CODES])
  const [ownTimes, setOwnTimes] = useState(false)
  const [times, setTimes] = useState<Record<ShiftCode, ShiftTime>>({
    morning: { start_time: '07:00', end_time: '12:00' },
    afternoon: { start_time: '13:00', end_time: '15:00' },
  })
  const [removing, setRemoving] = useState<HolidayException | null>(null)

  const save = useMutation({
    mutationFn: async (body: HolidayExceptionInput) =>
      (await api.put<HolidayExceptionWriteResult>(`/attendance/holidays/${holiday.id}/exceptions`, body)).data,
    onSuccess: () => {
      invalidateScheduling(queryClient)
      setAdding(false)
      setUsers([])
    },
  })
  const remove = useMutation({
    mutationFn: async (e: HolidayException) =>
      (await api.delete<HolidayExceptionWriteResult>(`/attendance/holidays/${holiday.id}/exceptions/${e.id}`)).data,
    onSuccess: () => {
      invalidateScheduling(queryClient)
      setRemoving(null)
    },
  })

  const shiftCodes = ownShifts ? codes : CODES
  const valid =
    users.length > 0 &&
    dates.length > 0 &&
    (!ownShifts || codes.length > 0) &&
    (!ownTimes || shiftCodes.every((c) => times[c].start_time < times[c].end_time))
  const body = (): HolidayExceptionInput => ({
    user_ids: users,
    dates,
    shift_codes: ownShifts ? codes : null,
    shift_times: ownTimes ? Object.fromEntries(shiftCodes.map((c) => [c, times[c]])) : null,
  })
  const shiftsText = (e: HolidayException) =>
    e.shifts.map((s) => `${t(`attendance.shiftsShort.${s.code}`)} ${s.start_time}–${s.end_time}`).join(', ') || '—'
  const toggle = <T,>(list: T[], value: T, on: boolean) => (on ? [...list, value] : list.filter((x) => x !== value))

  return (
    <section className="space-y-3 border-t border-stone-100 pt-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-stone-900">{t('attendance.holidayWork.title')}</h3>
        {!adding && days.length > 0 && (
          <Button variant="soft" onClick={() => setAdding(true)}>
            {t('attendance.holidayWork.add')}
          </Button>
        )}
      </div>
      {exceptions.isLoading ? (
        <Spinner className="text-brand-600" />
      ) : (exceptions.data ?? []).length === 0 ? (
        <p className="text-sm text-stone-500">{t('attendance.holidayWork.none')}</p>
      ) : (
        <ul className="divide-y divide-stone-100 rounded-xl ring-1 ring-stone-200">
          {exceptions.data!.map((e) => (
            <li key={e.id} className="flex items-start justify-between gap-2 px-3 py-2 text-sm">
              <span className="min-w-0">
                <span className="block font-medium text-stone-800">{e.user.full_name}</span>
                <span className="block tabular-nums text-stone-600">
                  {dayName(e.date)} · {shiftsText(e)}
                </span>
              </span>
              {e.date >= today && (
                <Button variant="ghost" className="text-red-700" onClick={() => setRemoving(e)}>
                  {t('attendance.holidayWork.remove')}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      {adding && (
        <div className="space-y-3 rounded-xl p-3 ring-1 ring-stone-200">
          <fieldset className="space-y-1">
            <legend className="text-sm font-medium text-stone-700">{t('attendance.holidayWork.employees')}</legend>
            <div className="max-h-48 space-y-1 overflow-y-auto rounded-lg p-2 ring-1 ring-inset ring-stone-200">
              {(employees.data?.items ?? []).map((row) => (
                <label key={row.user.id} className="flex cursor-pointer items-center gap-2 text-sm text-stone-800">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-stone-300 accent-brand-600"
                    checked={users.includes(row.user.id!)}
                    onChange={(e) => setUsers((u) => toggle(u, row.user.id!, e.target.checked))}
                  />
                  {row.user.full_name}
                  {row.workplace && <span className="text-xs text-stone-500">· {row.workplace.name}</span>}
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset className="space-y-1">
            <legend className="text-sm font-medium text-stone-700">{t('attendance.holidayWork.dates')}</legend>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {days.map((d) => (
                <label key={d} className="flex cursor-pointer items-center gap-2 text-sm text-stone-800">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-stone-300 accent-brand-600"
                    checked={dates.includes(d)}
                    onChange={(e) => setDates((list) => toggle(list, d, e.target.checked).sort())}
                  />
                  {dayName(d)}
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium text-stone-700">{t('attendance.employeeSchedules.shifts')}</legend>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-stone-800">
              <input type="radio" className="accent-brand-600" checked={!ownShifts} onChange={() => setOwnShifts(false)} />
              {t('attendance.holidayWork.normalShifts')}
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-stone-800">
              <input type="radio" className="accent-brand-600" checked={ownShifts} onChange={() => setOwnShifts(true)} />
              {t('attendance.holidayWork.chooseShifts')}
            </label>
            {ownShifts && (
              <div className="flex gap-4 pl-6">
                {CODES.map((c) => (
                  <label key={c} className="flex cursor-pointer items-center gap-2 text-sm text-stone-800">
                    <input
                      type="checkbox"
                      className="h-4 w-4 rounded border-stone-300 accent-brand-600"
                      checked={codes.includes(c)}
                      onChange={(e) => setCodes((list) => CODES.filter((x) => (x === c ? e.target.checked : list.includes(x))))}
                    />
                    {t(`attendance.shiftsShort.${c}`)}
                  </label>
                ))}
              </div>
            )}
            <label className="flex cursor-pointer items-center gap-2 text-sm text-stone-800">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-stone-300 accent-brand-600"
                checked={ownTimes}
                onChange={(e) => setOwnTimes(e.target.checked)}
              />
              {t('attendance.holidayWork.otherTimes')}
            </label>
            {ownTimes &&
              shiftCodes.map((c) => (
                <div key={c} className="flex flex-wrap items-center gap-2 pl-6">
                  <span className="w-full text-sm text-stone-800 sm:w-24">{t(`attendance.shiftsShort.${c}`)}</span>
                  {(['start_time', 'end_time'] as const).map((k, i) => (
                    <span key={k} className="flex items-center gap-2">
                      {i === 1 && <span className="text-stone-400">–</span>}
                      <TimeInput
                        value={times[c][k]}
                        aria-label={t(`attendance.employeeSchedules.${i ? 'end' : 'start'}`)}
                        onChange={(e) =>
                          e.target.value && setTimes((all) => ({ ...all, [c]: { ...all[c], [k]: e.target.value } }))
                        }
                      />
                    </span>
                  ))}
                </div>
              ))}
          </fieldset>
          {save.isError && <Alert tone="error">{errorMessage(save.error)}</Alert>}
          <div className={cx('flex justify-end gap-2')}>
            <Button variant="secondary" disabled={save.isPending} onClick={() => setAdding(false)}>
              {t('common.cancel')}
            </Button>
            <Button loading={save.isPending} disabled={!valid} onClick={() => save.mutate(body())}>
              {t('attendance.holidayWork.save')}
            </Button>
          </div>
        </div>
      )}

      {removing && (
        <ConfirmDialog
          open
          tone="danger"
          title={t('attendance.holidayWork.removeTitle')}
          body={[
            t('attendance.holidayWork.removeBody', { name: removing.user.full_name, date: dayName(removing.date) }),
            removing.date === today ? t('attendance.holidayWork.removeToday') : null,
          ]
            .filter(Boolean)
            .join(' ')}
          confirmLabel={t('attendance.holidayWork.remove')}
          loading={remove.isPending}
          error={remove.isError ? errorMessage(remove.error) : null}
          onConfirm={() => remove.mutate(removing)}
          onClose={() => {
            setRemoving(null)
            remove.reset()
          }}
        />
      )}
    </section>
  )
}
