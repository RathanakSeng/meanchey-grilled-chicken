import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui'
import { useFormatDate } from '@/lib/format'
import { paths } from '@/lib/paths'
import { REQUEST_MIN_MISSING_MINUTES, type AttendanceSummary } from '@/lib/types'
import { useDuration } from '../api'
import { useSplitText } from './parts'

/**
 * A slim strip under a month's KPI cards: the state of the month's request (approved, approved
 * with changes, pending, rejected), the Create request link when the window is open, or "No
 * request submitted" after the deadline. `mine`: the link and the lock hint are for the employee.
 */
export function RequestStrip({ summary, mine }: { summary: AttendanceSummary; mine: boolean }) {
  const { t } = useTranslation()
  const duration = useDuration()
  const splitText = useSplitText()
  const formatDate = useFormatDate()
  if (summary.period.month === null) return null
  const request = summary.request
  const balance = summary.kpis.balance_minutes
  const missing = Math.max(0, -balance)
  const eligible = missing >= REQUEST_MIN_MISSING_MINUTES

  let tone = 'bg-stone-50 text-stone-700 ring-stone-200'
  let content: React.ReactNode = null
  if (request?.status === 'approved') {
    tone = 'bg-green-50 text-green-800 ring-green-200'
    const cut = request.approved_salary_cut_minutes ?? 0
    const work = request.approved_unpaid_work_minutes ?? 0
    content = (
      <>
        <p>
          ✅ {t('attendance.requests.strip.approved', { split: splitText(cut, work) })}
          {request.reviewed_by && request.reviewed_at && (
            <span className="text-green-700">
              {' '}
              (
              {t('attendance.requests.strip.approvedBy', {
                name: request.reviewed_by.full_name,
                when: formatDate(request.reviewed_at, { dateStyle: 'medium' }),
              })}
              )
            </span>
          )}
        </p>
        {request.approved_with_changes && (
          <p className="text-xs">
            {t('attendance.requests.strip.changedFrom', {
              split: splitText(request.requested_salary_cut_minutes, request.requested_unpaid_work_minutes),
            })}
          </p>
        )}
        {request.review_comment && <p className="text-xs">“{request.review_comment}”</p>}
      </>
    )
  } else if (request?.status === 'pending') {
    tone = 'bg-amber-50 text-amber-900 ring-amber-200'
    content = <p>⏳ {t('attendance.requests.strip.pending')}</p>
  } else if (request?.status === 'rejected') {
    tone = 'bg-red-50 text-red-800 ring-red-200'
    content = <p>❌ {t('attendance.requests.strip.rejected', { reason: request.reject_reason ?? '' })}</p>
  } else if (summary.request_eligibility === 'eligible' && eligible) {
    tone = 'bg-brand-50 text-brand-900 ring-brand-200'
    content = (
      <p>
        {t('attendance.requests.strip.balance', { balance: duration(balance, true) })}{' '}
        {mine ? (
          <Link className="font-medium underline" to={paths.attendanceRequests}>
            {t('attendance.requests.create')}
          </Link>
        ) : (
          <span className="text-xs">{t('attendance.requests.strip.notYet')}</span>
        )}
      </p>
    )
  } else if (summary.request_eligibility === 'window_closed' && eligible) {
    content = <p>{t('attendance.requests.strip.noRequest')}</p>
  }
  if (!content && !summary.month_locked) return null
  return (
    <div className={`flex flex-wrap items-center justify-between gap-2 rounded-lg px-4 py-2.5 text-sm ring-1 ring-inset ${tone}`}>
      <div className="min-w-0">{content}</div>
      {summary.month_locked && <Badge tone="neutral">🔒 {t('attendance.requests.monthLocked')}</Badge>}
    </div>
  )
}
