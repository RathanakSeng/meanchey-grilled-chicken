import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useHasRole } from '@/auth/usePermission'
import { Alert, Button, Card, Field, Input } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import type { AttendanceRequestSettings } from '@/lib/types'
import { invalidateRequests, requestKeys, useRequestSettings } from './api'

const MIN_DAY = 1
const MAX_DAY = 28

/**
 * Attendance settings → "Request deadline (day of next month)": the last day on which a
 * month's missing-time request is accepted (1–28, default 7). Superadmin only.
 */
export function DeadlineCard() {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const queryClient = useQueryClient()
  const isSuperadmin = useHasRole('superadmin')
  const settings = useRequestSettings(isSuperadmin)
  const [day, setDay] = useState('7')
  const [saved, setSaved] = useState(false)
  useEffect(() => {
    if (settings.data) setDay(String(settings.data.request_deadline_day))
  }, [settings.data])

  const save = useMutation({
    mutationFn: async () =>
      (await api.put<AttendanceRequestSettings>('/attendance/settings/requests', { request_deadline_day: Number(day) }))
        .data,
    onSuccess: (data) => {
      queryClient.setQueryData(requestKeys.settings, data)
      invalidateRequests(queryClient)
      setSaved(true)
    },
  })
  if (!isSuperadmin) return null
  const valid = Number.isInteger(Number(day)) && Number(day) >= MIN_DAY && Number(day) <= MAX_DAY
  const submit = (e: FormEvent) => {
    e.preventDefault()
    setSaved(false)
    if (valid) save.mutate()
  }
  return (
    <Card title={t('attendance.requests.settings.title')}>
      <form onSubmit={submit} className="space-y-3">
        <Field label={t('attendance.requests.settings.deadline')} hint={t('attendance.requests.settings.hint')}>
          {(id) => (
            <Input
              id={id}
              type="number"
              inputMode="numeric"
              min={MIN_DAY}
              max={MAX_DAY}
              className="max-w-[8rem]"
              value={day}
              onChange={(e) => {
                setDay(e.target.value)
                setSaved(false)
              }}
            />
          )}
        </Field>
        {save.isError && <Alert tone="error">{errorMessage(save.error)}</Alert>}
        {saved && <Alert tone="success">{t('attendance.requests.settings.saved')}</Alert>}
        <Button
          type="submit"
          loading={save.isPending}
          disabled={!valid || String(settings.data?.request_deadline_day) === day}
        >
          {t('common.save')}
        </Button>
      </form>
    </Card>
  )
}
