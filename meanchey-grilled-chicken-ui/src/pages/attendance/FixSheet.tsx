import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { SegmentedControl } from '@/components/SegmentedControl'
import { Sheet } from '@/components/Sheet'
import { Alert, Button, Field, Input } from '@/components/ui'
import { api } from '@/lib/api'
import { ClientError, useErrorMessage } from '@/lib/errors'
import type {
  AttendanceDayCell,
  AttendanceDayRow,
  AttendanceDayShift,
  AttendanceRecord,
  CheckoutStatus,
} from '@/lib/types'
import { clockTime, invalidateAttendance, useShiftName, useStatusText } from './api'

/** From Today (a day row and the shift's times) or an employee's history (the record only). */
export interface FixTarget {
  row: Pick<AttendanceDayRow, 'user'>
  shift: Pick<AttendanceDayShift, 'code'> & Partial<Pick<AttendanceDayShift, 'start' | 'end'>>
  cell?: Pick<AttendanceDayCell, 'record'>
  date: string
}

type Attended = 'attended' | 'absent'
type Checkout = 'open' | CheckoutStatus

/**
 * Fix a record (PATCH) or add a missing one (POST), always with a reason. Present / late follows
 * from the check-in time (the API recalculates late minutes from the shift's snapshot start).
 * The original values are shown above the form.
 */
export function FixSheet({ target, timezone, onClose }: { target: FixTarget; timezone: string; onClose(): void }) {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const shiftName = useShiftName()
  const statusText = useStatusText()
  const queryClient = useQueryClient()
  const formId = useId()
  const record = target.cell?.record ?? null

  const [attended, setAttended] = useState<Attended>(record?.status === 'absent' ? 'absent' : 'attended')
  const [checkIn, setCheckIn] = useState(record?.check_in_at ? clockTime(record.check_in_at, timezone) : '')
  const [checkout, setCheckout] = useState<Checkout>(record?.checkout_status ?? 'open')
  const [checkOut, setCheckOut] = useState(record?.check_out_at ? clockTime(record.check_out_at, timezone) : '')
  const [reason, setReason] = useState('')

  const save = useMutation({
    mutationFn: async () => {
      if (!reason.trim()) throw new ClientError('ATTENDANCE_REASON_REQUIRED')
      if (attended === 'attended' && !checkIn) throw new ClientError('ATTENDANCE_TIME_REQUIRED')
      if (attended === 'attended' && checkout === 'checked_out' && !checkOut) {
        throw new ClientError('ATTENDANCE_TIME_REQUIRED')
      }
      const body =
        attended === 'absent'
          ? { status: 'absent', reason: reason.trim() }
          : {
              status: 'present',
              check_in_time: checkIn,
              check_out_time: checkout === 'checked_out' ? checkOut : null,
              checkout_status: checkout === 'open' ? null : checkout,
              reason: reason.trim(),
            }
      if (record) return (await api.patch<AttendanceRecord>(`/attendance/records/${record.id}`, body)).data
      return (
        await api.post<AttendanceRecord>('/attendance/records', {
          ...body,
          user_id: target.row.user.id,
          work_date: target.date,
          shift_code: target.shift.code,
        })
      ).data
    },
    onSuccess: () => {
      invalidateAttendance(queryClient)
      onClose()
    },
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }

  return (
    <Sheet
      open
      busy={save.isPending}
      onClose={onClose}
      title={t(record ? 'attendance.fix.titleFix' : 'attendance.fix.titleAdd', {
        name: target.row.user.full_name,
        shift: shiftName(target.shift.code),
      })}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={save.isPending}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" form={formId} loading={save.isPending}>
            {t('common.save')}
          </Button>
        </div>
      }
    >
      <form id={formId} onSubmit={submit} className="space-y-4">
        <div className="rounded-lg bg-stone-50 p-3 text-sm text-stone-600">
          <p className="font-medium text-stone-800">{t('attendance.fix.original')}</p>
          {record ? (
            <p>
              {statusText(record)}
              {record.check_in_at &&
                ` · ${t('attendance.inOut', {
                  in: clockTime(record.check_in_at, timezone),
                  out:
                    record.checkout_status === 'forgot_checkout'
                      ? t('attendance.status.forgot_checkout')
                      : clockTime(record.check_out_at, timezone),
                })}`}
              {record.corrected && record.correction_reason && ` · “${record.correction_reason}”`}
            </p>
          ) : (
            <p>{t('attendance.fix.noRecord')}</p>
          )}
          {(record || target.shift.start) && (
            <p className="text-xs">
              {t('attendance.fix.shiftTimes', {
                start: clockTime(record?.scheduled_start ?? target.shift.start, timezone),
                end: clockTime(record?.scheduled_end ?? target.shift.end, timezone),
              })}
            </p>
          )}
        </div>

        <p className="-mb-3 text-sm font-medium text-stone-700">{t('attendance.fix.status')}</p>
        <SegmentedControl<Attended>
          label={t('attendance.fix.status')}
          value={attended}
          onChange={setAttended}
          segments={[
            { value: 'attended', label: t('attendance.fix.attended') },
            { value: 'absent', label: t('attendance.status.absent') },
          ]}
        />

        {attended === 'attended' && (
          <>
            <Field label={t('attendance.fields.checkIn')} hint={t('attendance.fix.lateHint')}>
              {(id) => <Input id={id} type="time" value={checkIn} onChange={(e) => setCheckIn(e.target.value)} required />}
            </Field>
            <p className="-mb-3 text-sm font-medium text-stone-700">{t('attendance.fields.checkOut')}</p>
            <SegmentedControl<Checkout>
              label={t('attendance.fields.checkOut')}
              value={checkout}
              onChange={setCheckout}
              segments={[
                { value: 'checked_out', label: t('attendance.fix.checkoutDone') },
                { value: 'forgot_checkout', label: t('attendance.fix.checkoutForgot') },
                { value: 'open', label: t('attendance.fix.notYet') },
              ]}
            />
            {checkout === 'checked_out' && (
              <Field label={t('attendance.fix.checkOutTime')}>
                {(id) => (
                  <Input id={id} type="time" value={checkOut} onChange={(e) => setCheckOut(e.target.value)} required />
                )}
              </Field>
            )}
          </>
        )}

        <Field label={t('attendance.fix.reason')} hint={t('attendance.fix.reasonHint')}>
          {(id) => (
            <Input id={id} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} required />
          )}
        </Field>

        {save.isError && <Alert tone="error">{errorMessage(save.error)}</Alert>}
      </form>
    </Sheet>
  )
}
