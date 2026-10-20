import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAuth } from '@/auth/AuthProvider'
import { usePermission } from '@/auth/usePermission'
import { Sheet } from '@/components/Sheet'
import { Alert, Button, Field, Input, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useFormatDate } from '@/lib/format'
import { paths } from '@/lib/paths'
import { REQUEST_TEXT_MAX_LENGTH, type AttendanceRequest } from '@/lib/types'
import { useDuration } from '../api'
import { invalidateRequests, REVIEW_PERMISSION, useRequest } from './api'
import { RequestStatusBadge, SplitEditor, useMonthText, useSplitText } from './parts'

type Mode = 'view' | 'approve' | 'changes' | 'reject'

/**
 * One request: the month's figures as they were when it was sent, the requested and approved
 * split, the note and the decision. A reviewer (attendance.requests_review, never on their own
 * request) with a pending one gets Approve, Approve with changes (another split, a comment)
 * and Reject (a reason).
 */
export function RequestSheet({ id, onClose }: { id: string; onClose(): void }) {
  const { t } = useTranslation()
  const request = useRequest(id)
  const errorMessage = useErrorMessage()
  const monthText = useMonthText()
  const data = request.data
  return (
    <Sheet
      open
      onClose={onClose}
      title={data ? t('attendance.requests.detailTitle', { month: monthText(data.year, data.month) }) : t('common.loading')}
    >
      {request.isError ? (
        <Alert tone="error">{errorMessage(request.error)}</Alert>
      ) : !data ? (
        <div className="flex justify-center py-10 text-brand-600">
          <Spinner />
        </div>
      ) : (
        <Body request={data} onClose={onClose} />
      )}
    </Sheet>
  )
}

function Body({ request, onClose }: { request: AttendanceRequest; onClose(): void }) {
  const { t } = useTranslation()
  const { me } = useAuth()
  const duration = useDuration()
  const splitText = useSplitText()
  const formatDate = useFormatDate()
  const canReview = usePermission(REVIEW_PERMISSION)
  const canViewAttendance = usePermission('attendance.view')
  const [mode, setMode] = useState<Mode>('view')
  const mine = me?.user.id === request.user.id
  const reviewable = canReview && !mine && request.status === 'pending'

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-medium text-stone-900">{request.user.full_name}</p>
          {request.position && <p className="text-xs text-stone-500">{request.position}</p>}
        </div>
        <RequestStatusBadge request={request} />
      </div>

      <dl className="grid grid-cols-2 gap-3 rounded-lg bg-stone-50 p-3 text-sm">
        <Fact label={t('attendance.requests.absent')} value={duration(request.absent_minutes)} />
        <Fact label={t('attendance.requests.late')} value={duration(request.late_minutes)} />
        <Fact label={t('attendance.requests.extra')} value={duration(request.extra_minutes)} />
        <Fact label={t('attendance.requests.missing')} value={duration(request.missing_minutes)} strong />
        <Fact
          label={t('attendance.kpis.balance')}
          value={duration(request.balance_minutes, true)}
          className="col-span-2"
        />
      </dl>
      <p className="-mt-2 text-xs text-stone-500">{t('attendance.requests.snapshotHint')}</p>

      <Section title={t('attendance.requests.requested')}>
        {splitText(request.requested_salary_cut_minutes, request.requested_unpaid_work_minutes)}
        <span className="block text-xs text-stone-500">
          {t('attendance.requests.sentAt', { when: formatDate(request.submitted_at) })}
        </span>
      </Section>
      {request.note && <Section title={t('attendance.requests.noteShown')}>{request.note}</Section>}

      {request.status === 'approved' &&
        request.approved_salary_cut_minutes !== null &&
        request.approved_unpaid_work_minutes !== null && (
          <Section title={t('attendance.requests.approvedSplit')}>
            {splitText(request.approved_salary_cut_minutes, request.approved_unpaid_work_minutes)}
            {request.approved_with_changes && (
              <span className="block text-xs text-stone-500">{t('attendance.requests.changedFromShort')}</span>
            )}
          </Section>
        )}
      {request.review_comment && <Section title={t('attendance.requests.comment')}>{request.review_comment}</Section>}
      {request.reject_reason && (
        <Section title={t('attendance.requests.rejectedBecause')}>{request.reject_reason}</Section>
      )}
      {request.reviewed_by && request.reviewed_at && (
        <p className="text-xs text-stone-500">
          {t('attendance.requests.reviewedBy', {
            name: request.reviewed_by.full_name,
            when: formatDate(request.reviewed_at),
          })}
        </p>
      )}
      {request.month_locked && <p className="text-xs text-stone-600">🔒 {t('attendance.requests.lockedHint')}</p>}
      {canViewAttendance && !mine && request.user.id && (
        <Link
          className="inline-block text-sm font-medium text-brand-700 hover:underline"
          to={`${paths.attendanceEmployee(request.user.id)}?year=${request.year}&month=${request.month}`}
          onClick={onClose}
        >
          {t('attendance.requests.openAttendance')} →
        </Link>
      )}

      {reviewable &&
        (mode === 'view' ? (
          <div className="flex flex-wrap gap-2 border-t border-stone-100 pt-4">
            <Button onClick={() => setMode('approve')}>{t('attendance.requests.approve')}</Button>
            <Button variant="secondary" onClick={() => setMode('changes')}>
              {t('attendance.requests.approveChanges')}
            </Button>
            <Button variant="danger" onClick={() => setMode('reject')}>
              {t('attendance.requests.reject')}
            </Button>
          </div>
        ) : (
          <ReviewForm request={request} mode={mode} onCancel={() => setMode('view')} onDone={onClose} />
        ))}
    </div>
  )
}

function Fact({
  label,
  value,
  strong = false,
  className,
}: {
  label: string
  value: string
  strong?: boolean
  className?: string
}) {
  return (
    <div className={className}>
      <dt className="text-xs text-stone-500">{label}</dt>
      <dd className={strong ? 'font-semibold text-red-700' : 'text-stone-800'}>{value}</dd>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-stone-500">{title}</p>
      <p className="mt-0.5 text-sm text-stone-800">{children}</p>
    </div>
  )
}

function ReviewForm({
  request,
  mode,
  onCancel,
  onDone,
}: {
  request: AttendanceRequest
  mode: Exclude<Mode, 'view'>
  onCancel(): void
  onDone(): void
}) {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const queryClient = useQueryClient()
  const formId = useId()
  const [split, setSplit] = useState({
    salaryCut: request.requested_salary_cut_minutes,
    unpaidWork: request.requested_unpaid_work_minutes,
  })
  const [text, setText] = useState('')
  const matches = split.salaryCut + split.unpaidWork === request.missing_minutes
  const base = `/attendance/requests/${request.id}`

  const send = useMutation({
    mutationFn: async () => {
      if (mode === 'reject') return (await api.post<AttendanceRequest>(`${base}/reject`, { reason: text.trim() })).data
      const comment = text.trim() ? { comment: text.trim() } : {}
      const splitBody =
        mode === 'changes' ? { salary_cut_minutes: split.salaryCut, unpaid_work_minutes: split.unpaidWork } : {}
      return (await api.post<AttendanceRequest>(`${base}/approve`, { ...splitBody, ...comment })).data
    },
    onSuccess: () => {
      invalidateRequests(queryClient)
      onDone()
    },
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    send.mutate()
  }
  const disabled = (mode === 'changes' && !matches) || (mode === 'reject' && !text.trim())

  return (
    <form id={formId} onSubmit={submit} className="space-y-4 border-t border-stone-100 pt-4">
      <p className="text-sm font-medium text-stone-800">
        {t(
          mode === 'approve'
            ? 'attendance.requests.approve'
            : mode === 'changes'
              ? 'attendance.requests.approveChanges'
              : 'attendance.requests.reject',
        )}
      </p>
      {mode === 'changes' && (
        <SplitEditor
          missing={request.missing_minutes}
          salaryCut={split.salaryCut}
          unpaidWork={split.unpaidWork}
          onChange={setSplit}
          disabled={send.isPending}
        />
      )}
      <Field
        label={t(mode === 'reject' ? 'attendance.requests.rejectReason' : 'attendance.requests.commentOptional')}
      >
        {(id) => (
          <Input
            id={id}
            value={text}
            maxLength={REQUEST_TEXT_MAX_LENGTH}
            required={mode === 'reject'}
            onChange={(e) => setText(e.target.value)}
          />
        )}
      </Field>
      {send.isError && <Alert tone="error">{errorMessage(send.error)}</Alert>}
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel} disabled={send.isPending}>
          {t('common.cancel')}
        </Button>
        <Button
          type="submit"
          variant={mode === 'reject' ? 'danger' : 'primary'}
          loading={send.isPending}
          disabled={disabled}
        >
          {t(mode === 'reject' ? 'attendance.requests.reject' : 'attendance.requests.confirmApprove')}
        </Button>
      </div>
    </form>
  )
}
