import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useNavigate } from 'react-router-dom'
import { Icon } from '@/components/icons'
import { Alert, Button, PageHeader, Spinner, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { paths } from '@/lib/paths'
import type { AttendanceAction, AttendanceToday, CheckResult } from '@/lib/types'
import { TrackingNotice } from './AttendanceCard'
import { attendanceKeys, clockTime, invalidateAttendance, useAttendanceToday, useShiftName } from './api'
import { distanceM, useDeviceLocation, type Position } from './location'
import { MapView } from './MapView'

/**
 * The check screen (`/attendance/check`, opened by reminders, /checkin, /checkout, the Home card
 * and My attendance). It shows the ONE action the API decides (`next_action`; an `?action=` from
 * older links is ignored), starts reading the GPS position at once, shows it on the map against
 * the workplace radius, and enables Confirm only inside the radius with acceptable accuracy.
 * After a check (or with nothing to do) it goes to the Attendance page, which shows the result.
 */
export function CheckPage() {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const today = useAttendanceToday()
  const navigate = useNavigate()

  return (
    <div className="mx-auto max-w-xl">
      <PageHeader title={t('attendance.check.title')} back={paths.attendance} />
      {today.isLoading ? (
        <div className="flex justify-center py-16 text-brand-600">
          <Spinner />
        </div>
      ) : today.data && (today.data.starts_on || !today.data.tracked) ? (
        <TrackingNotice today={today.data} />
      ) : today.data ? (
        <CheckForm today={today.data} onDone={() => navigate(paths.attendance, { replace: true })} />
      ) : (
        <Alert tone="error">{errorMessage(today.error)}</Alert>
      )}
    </div>
  )
}

function CheckForm({ today, onDone }: { today: AttendanceToday; onDone(result: CheckResult): void }) {
  const { t } = useTranslation()
  const shiftName = useShiftName()
  const errorMessage = useErrorMessage()
  const queryClient = useQueryClient()
  const { state, refresh, openSettings } = useDeviceLocation()
  const na = today.next_action
  const workplace = today.workplace
  const action = na.action === 'none' ? null : na.action

  const submit = useMutation({
    mutationFn: async ({ action, position }: { action: AttendanceAction; position: Position }) => {
      const url = action === 'check_in' ? '/attendance/check-in' : '/attendance/check-out'
      const body = { latitude: position.latitude, longitude: position.longitude, accuracy_m: position.accuracy }
      return (await api.post<CheckResult>(url, body)).data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(attendanceKeys.meToday, data.today)
      invalidateAttendance(queryClient)
      onDone(data)
    },
    onError: () => {
      // The window or the record may have changed: show the API's current next action.
      void queryClient.invalidateQueries({ queryKey: attendanceKeys.meToday })
    },
  })

  const position = state.status === 'ok' ? state.position : state.status === 'locating' ? state.position : undefined
  const mapWorkplace = useMemo(
    () =>
      workplace?.has_coordinates && workplace.latitude !== null && workplace.longitude !== null
        ? { latitude: workplace.latitude, longitude: workplace.longitude, radius: workplace.radius_m }
        : null,
    [workplace],
  )
  const mapUser = useMemo(
    () => (position ? { latitude: position.latitude, longitude: position.longitude, accuracy: position.accuracy } : null),
    [position],
  )
  const distance =
    position && mapWorkplace
      ? Math.round(distanceM(mapWorkplace.latitude, mapWorkplace.longitude, position.latitude, position.longitude))
      : null
  const inside = distance !== null && mapWorkplace !== null && distance <= mapWorkplace.radius
  const accurate = position !== undefined && position.accuracy <= today.max_accuracy_m
  const canConfirm = action !== null && state.status === 'ok' && inside && accurate && !submit.isPending

  if (!action) return <Navigate to={paths.attendance} replace />

  return (
    <div className="space-y-4">
      <div
        className={cx(
          'rounded-2xl px-4 py-3 text-white',
          action === 'check_in' ? 'bg-brand-600' : 'bg-sky-600',
        )}
      >
        <p className="text-lg font-semibold">
          {t(`attendance.check.heading.${action}`, { shift: shiftName(na.shift_code) })}
        </p>
        <p className="text-sm text-white/85">
          {t('attendance.check.openUntil', { time: clockTime(na.until, today.timezone) })}
        </p>
      </div>

      {!mapWorkplace ? (
        <Alert tone="error">{t('errors.ATTENDANCE_WORKPLACE_NOT_SET')}</Alert>
      ) : (
        <MapView workplace={mapWorkplace} user={mapUser} className="isolate z-0 h-72 w-full overflow-hidden rounded-xl ring-1 ring-stone-200" />
      )}

      <LocationStatus
        status={state.status}
        distance={distance}
        inside={inside}
        accurate={accurate}
        accuracy={position?.accuracy}
        maxAccuracy={today.max_accuracy_m}
        radius={mapWorkplace?.radius}
        workplaceName={workplace?.name ?? ''}
        onOpenSettings={state.status === 'denied' ? openSettings : undefined}
      />

      {submit.isError && <Alert tone="error">{errorMessage(submit.error)}</Alert>}

      <div className="space-y-2">
        <Button
          block
          className="py-4 text-base"
          disabled={!canConfirm}
          loading={submit.isPending}
          onClick={() => position && submit.mutate({ action, position })}
        >
          <Icon name="check" />
          {t(`attendance.check.confirm.${action}`)}
        </Button>
        <Button
          block
          variant="secondary"
          disabled={state.status === 'locating'}
          onClick={() => {
            submit.reset()
            void refresh()
          }}
        >
          <Icon name="locate" />
          {t('attendance.check.refresh')}
        </Button>
      </div>
    </div>
  )
}

function LocationStatus({
  status,
  distance,
  inside,
  accurate,
  accuracy,
  maxAccuracy,
  radius,
  workplaceName,
  onOpenSettings,
}: {
  status: string
  distance: number | null
  inside: boolean
  accurate: boolean
  accuracy?: number
  maxAccuracy: number
  radius?: number
  workplaceName: string
  onOpenSettings?: () => void
}) {
  const { t } = useTranslation()
  if (status === 'denied') {
    return (
      <Alert tone="error">
        <p>{t('attendance.check.denied')}</p>
        {onOpenSettings && (
          <Button variant="secondary" className="mt-2" onClick={onOpenSettings}>
            {t('attendance.check.openSettings')}
          </Button>
        )}
      </Alert>
    )
  }
  if (status === 'unavailable') return <Alert tone="error">{t('attendance.check.unavailable')}</Alert>
  if (status === 'locating' && distance === null) {
    return (
      <p className="flex items-center gap-2 text-sm text-stone-600">
        <Spinner className="h-4 w-4" />
        {t('attendance.check.locating')}
      </p>
    )
  }
  if (distance === null) return null
  return (
    <div className="space-y-1 text-sm font-medium" aria-live="polite">
      <p className={inside ? 'text-green-700' : 'text-red-700'}>
        {inside
          ? t('attendance.check.inside', { distance, name: workplaceName })
          : t('attendance.check.outside', { distance, radius })}
      </p>
      {accuracy !== undefined && !accurate && (
        <p className="text-red-700">
          {t('attendance.check.inaccurate', { accuracy: Math.round(accuracy), max: maxAccuracy })}
        </p>
      )}
      {status === 'locating' && <p className="text-xs font-normal text-stone-500">{t('attendance.check.locating')}</p>}
    </div>
  )
}
