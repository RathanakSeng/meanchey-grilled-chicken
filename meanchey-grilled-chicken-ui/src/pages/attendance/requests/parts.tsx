import { useTranslation } from 'react-i18next'
import { Badge, Field, Input } from '@/components/ui'
import { useCalendarNames } from '@/lib/format'
import type { AttendanceRequestBrief, RequestStatus, RequestType } from '@/lib/types'
import { useDuration } from '../api'

/** "Salary cut 2 h · unpaid extra work 4 h 45" (a zero part is left out). */
export function useSplitText() {
  const { t } = useTranslation()
  const duration = useDuration()
  return (salaryCut: number, unpaidWork: number): string =>
    [
      salaryCut > 0 && t('attendance.requests.splitCut', { duration: duration(salaryCut) }),
      unpaidWork > 0 && t('attendance.requests.splitWork', { duration: duration(unpaidWork) }),
    ]
      .filter(Boolean)
      .join(' · ')
}

/** "October 2026". */
export function useMonthText() {
  const names = useCalendarNames()
  return (year: number, month: number) => `${names.month(month)} ${year}`
}

type Reviewed = Pick<AttendanceRequestBrief, 'status' | 'approved_with_changes'>

export function RequestStatusBadge({ request }: { request: Reviewed }) {
  const { t } = useTranslation()
  if (request.status === 'approved') {
    return (
      <Badge tone="green">
        {t(request.approved_with_changes ? 'attendance.requests.status.approvedChanges' : 'attendance.requests.status.approved')}
      </Badge>
    )
  }
  return (
    <Badge tone={request.status === 'pending' ? 'amber' : 'red'}>
      {t(`attendance.requests.status.${request.status}`)}
    </Badge>
  )
}

export function statusEmoji(status: RequestStatus): string {
  return status === 'approved' ? '✅' : status === 'rejected' ? '❌' : '⏳'
}

export function typeLabelKey(type: RequestType): string {
  return `attendance.requests.type.${type}`
}

/** Hours and minutes inputs for a number of minutes. Minutes above 59 carry into the hours. */
export function DurationInput({
  label,
  value,
  onChange,
  disabled = false,
}: {
  label: string
  value: number
  onChange(minutes: number): void
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const hours = Math.floor(value / 60)
  const minutes = value % 60
  const clean = (raw: string) => Math.min(Math.max(0, Math.floor(Number(raw) || 0)), 999)
  return (
    <Field label={label}>
      {(id) => (
        <div className="flex items-center gap-2">
          <Input
            id={id}
            type="number"
            inputMode="numeric"
            min={0}
            max={999}
            value={hours}
            disabled={disabled}
            aria-label={`${label}: ${t('attendance.requests.hours')}`}
            onChange={(e) => onChange(clean(e.target.value) * 60 + minutes)}
          />
          <span className="text-sm text-stone-500">{t('attendance.requests.hoursShort')}</span>
          <Input
            type="number"
            inputMode="numeric"
            min={0}
            max={59}
            value={minutes}
            disabled={disabled}
            aria-label={`${label}: ${t('attendance.requests.minutes')}`}
            onChange={(e) => onChange(hours * 60 + Math.min(clean(e.target.value), 59))}
          />
          <span className="text-sm text-stone-500">{t('attendance.requests.minutesShort')}</span>
        </div>
      )}
    </Field>
  )
}

/**
 * Salary cut and unpaid extra work, which must add up to the missing time: two inputs in hours
 * and minutes, quick "all one" buttons and a live "Covered X of Y" line.
 */
export function SplitEditor({
  missing,
  salaryCut,
  unpaidWork,
  onChange,
  disabled = false,
}: {
  missing: number
  salaryCut: number
  unpaidWork: number
  onChange(next: { salaryCut: number; unpaidWork: number }): void
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const duration = useDuration()
  const covered = salaryCut + unpaidWork
  const matches = covered === missing
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={disabled}
          className="rounded-full bg-stone-100 px-3 py-1 text-xs font-medium text-stone-700 hover:bg-stone-200 disabled:opacity-60"
          onClick={() => onChange({ salaryCut: missing, unpaidWork: 0 })}
        >
          {t('attendance.requests.allSalaryCut')}
        </button>
        <button
          type="button"
          disabled={disabled}
          className="rounded-full bg-stone-100 px-3 py-1 text-xs font-medium text-stone-700 hover:bg-stone-200 disabled:opacity-60"
          onClick={() => onChange({ salaryCut: 0, unpaidWork: missing })}
        >
          {t('attendance.requests.allUnpaidWork')}
        </button>
      </div>
      <DurationInput
        label={t('attendance.requests.salaryCut')}
        value={salaryCut}
        disabled={disabled}
        onChange={(m) => onChange({ salaryCut: m, unpaidWork })}
      />
      <DurationInput
        label={t('attendance.requests.unpaidWork')}
        value={unpaidWork}
        disabled={disabled}
        onChange={(m) => onChange({ salaryCut, unpaidWork: m })}
      />
      <p role="status" className={matches ? 'text-sm font-medium text-green-700' : 'text-sm font-medium text-red-700'}>
        {t('attendance.requests.covered', { covered: duration(covered), missing: duration(missing) })}
        {matches ? ' ✅' : ''}
      </p>
    </div>
  )
}
