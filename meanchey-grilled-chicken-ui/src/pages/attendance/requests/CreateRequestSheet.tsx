import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Sheet } from '@/components/Sheet'
import { Alert, Button, Field, Input } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useFormatDay } from '@/lib/format'
import { REQUEST_TEXT_MAX_LENGTH, type AttendanceRequest, type MyRequestMonth } from '@/lib/types'
import { useDuration } from '../api'
import { invalidateRequests } from './api'
import { SplitEditor, useMonthText } from './parts'

/**
 * Create the month's request: the month's numbers, the split (salary cut + unpaid extra work =
 * the missing time, live "Covered X of Y"), an optional note. One request per month, so Submit
 * is enabled only when the split matches.
 */
export function CreateRequestSheet({ month, onClose }: { month: MyRequestMonth; onClose(): void }) {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const duration = useDuration()
  const monthText = useMonthText()
  const formatDay = useFormatDay()
  const queryClient = useQueryClient()
  const formId = useId()
  const missing = month.missing_minutes
  // Start with everything as unpaid extra work; most people would rather make the time up.
  const [split, setSplit] = useState({ salaryCut: 0, unpaidWork: missing })
  const [note, setNote] = useState('')
  const matches = split.salaryCut + split.unpaidWork === missing

  const submit = useMutation({
    mutationFn: async () =>
      (
        await api.post<AttendanceRequest>('/attendance/requests', {
          year: month.year,
          month: month.month,
          salary_cut_minutes: split.salaryCut,
          unpaid_work_minutes: split.unpaidWork,
          ...(note.trim() ? { note: note.trim() } : {}),
        })
      ).data,
    onSuccess: () => {
      invalidateRequests(queryClient)
      onClose()
    },
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (matches) submit.mutate()
  }

  return (
    <Sheet
      open
      busy={submit.isPending}
      onClose={onClose}
      title={t('attendance.requests.createTitle', { month: monthText(month.year, month.month) })}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={submit.isPending}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" form={formId} loading={submit.isPending} disabled={!matches}>
            {t('attendance.requests.submit')}
          </Button>
        </div>
      }
    >
      <form id={formId} onSubmit={onSubmit} className="space-y-4">
        <dl className="grid grid-cols-2 gap-2 rounded-lg bg-stone-50 p-3 text-sm">
          <Stat label={t('attendance.requests.absent')} value={duration(month.absent_minutes)} />
          <Stat label={t('attendance.requests.late')} value={duration(month.late_minutes)} />
          <Stat label={t('attendance.requests.extra')} value={duration(month.extra_minutes)} />
          <Stat label={t('attendance.requests.missing')} value={duration(missing)} strong />
        </dl>
        <p className="text-xs text-stone-500">
          {t('attendance.requests.createHint', { date: formatDay(month.closes) })}
        </p>

        <SplitEditor missing={missing} salaryCut={split.salaryCut} unpaidWork={split.unpaidWork} onChange={setSplit} />

        <Field label={t('attendance.requests.note')}>
          {(id) => (
            <Input
              id={id}
              value={note}
              maxLength={REQUEST_TEXT_MAX_LENGTH}
              onChange={(e) => setNote(e.target.value)}
            />
          )}
        </Field>
        <Alert tone="warning">{t('attendance.requests.onlyOne')}</Alert>
        {submit.isError && <Alert tone="error">{errorMessage(submit.error)}</Alert>}
      </form>
    </Sheet>
  )
}

function Stat({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-stone-500">{label}</dt>
      <dd className={strong ? 'font-semibold text-red-700' : 'text-stone-800'}>{value}</dd>
    </div>
  )
}
