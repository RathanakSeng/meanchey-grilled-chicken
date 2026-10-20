import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '@/auth/AuthProvider'
import { usePermission } from '@/auth/usePermission'
import { SegmentedControl } from '@/components/SegmentedControl'
import { Alert, Badge, Button, Card, EmptyState, Field, PageHeader, Select, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useCalendarNames, useFormatDate, useFormatDay } from '@/lib/format'
import { paths } from '@/lib/paths'
import type {
  AttendanceRequestRow,
  MyRequestMonth,
  Page,
  RequestStatus,
  User,
} from '@/lib/types'
import { useDuration, useHasAttendance } from '../api'
import {
  currentYearMonth,
  monthState,
  REVIEW_PERMISSION,
  useMyRequests,
  usePendingRequestCount,
  useRequestList,
  type RequestListParams,
} from './api'
import { CreateRequestSheet } from './CreateRequestSheet'
import { RequestSheet } from './RequestSheet'
import { RequestStatusBadge, useMonthText, useSplitText } from './parts'

type Tab = 'mine' | 'review' | 'all'

/**
 * Attendance → Requests. Tracked employees: the months of a year with their state and the
 * Create request action. Reviewers (attendance.requests_review): "To review" (pending, oldest
 * first) and "All" (month, status incl. No request, employee). `?request=<id>` opens a request
 * (the Telegram button); `?tab=` picks the tab.
 */
export function RequestsPage() {
  const { t } = useTranslation()
  const tracked = useHasAttendance()
  const canReview = usePermission(REVIEW_PERMISSION)
  const pending = usePendingRequestCount()
  const [params, setParams] = useSearchParams()
  const tabs: Tab[] = [...(tracked ? (['mine'] as const) : []), ...(canReview ? (['review', 'all'] as const) : [])]
  const asked = params.get('tab') as Tab | null
  const tab: Tab = asked && tabs.includes(asked) ? asked : (canReview && pending > 0 ? 'review' : tabs[0])
  const openId = params.get('request')

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    setParams(next, { replace: true })
  }

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title={t('attendance.requests.title')} subtitle={t('attendance.requests.subtitle')} back={paths.attendance} />
      {tabs.length > 1 && (
        <div className="mb-4">
          <SegmentedControl<Tab>
            label={t('attendance.requests.title')}
            value={tab}
            onChange={(value) => update({ tab: value, request: null })}
            segments={tabs.map((value) => ({
              value,
              label:
                value === 'mine'
                  ? t('attendance.requests.tabs.mine')
                  : value === 'review'
                    ? `${t('attendance.requests.tabs.review')}${pending > 0 ? ` (${pending})` : ''}`
                    : t('attendance.requests.tabs.all'),
            }))}
          />
        </div>
      )}
      {tab === 'mine' && <MyRequests onOpen={(id) => update({ request: id })} />}
      {(tab === 'review' || tab === 'all') && <ReviewList all={tab === 'all'} onOpen={(id) => update({ request: id })} />}
      {openId && <RequestSheet id={openId} onClose={() => update({ request: null })} />}
    </div>
  )
}

// --- My requests ---------------------------------------------------------------------------------

function MyRequests({ onOpen }: { onOpen(id: string): void }) {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const now = currentYearMonth()
  const [year, setYear] = useState(now.year)
  const query = useMyRequests(year)
  const [creating, setCreating] = useState<MyRequestMonth | null>(null)
  const years = [now.year, now.year - 1, now.year - 2]
  return (
    <div className="space-y-3">
      <div className="max-w-[10rem]">
        <Field label={t('attendance.mine.year')}>
          {(id) => (
            <Select id={id} value={year} onChange={(e) => setYear(Number(e.target.value))}>
              {years.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      {query.isError && <Alert tone="error">{errorMessage(query.error)}</Alert>}
      {query.isLoading ? (
        <div className="flex justify-center py-12 text-brand-600">
          <Spinner />
        </div>
      ) : !query.data?.months.length ? (
        <Card>
          <EmptyState>{t('attendance.requests.emptyMine')}</EmptyState>
        </Card>
      ) : (
        <ul className="space-y-2">
          {query.data.months.map((m) => (
            <MonthCard key={`${m.year}-${m.month}`} month={m} onCreate={() => setCreating(m)} onOpen={onOpen} />
          ))}
        </ul>
      )}
      {creating && <CreateRequestSheet month={creating} onClose={() => setCreating(null)} />}
    </div>
  )
}

function MonthCard({
  month,
  onCreate,
  onOpen,
}: {
  month: MyRequestMonth
  onCreate(): void
  onOpen(id: string): void
}) {
  const { t } = useTranslation()
  const duration = useDuration()
  const monthText = useMonthText()
  const splitText = useSplitText()
  const formatDay = useFormatDay()
  const state = monthState(month.eligibility, month.request)
  const request = month.request
  const approved = request?.approved_salary_cut_minutes !== null && request?.approved_salary_cut_minutes !== undefined
  return (
    <li>
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="font-medium text-stone-900">{monthText(month.year, month.month)}</p>
            <p className="text-sm text-stone-600">
              {t('attendance.kpis.balance')}:{' '}
              <span className={month.balance_minutes < 0 ? 'font-medium text-red-700' : undefined}>
                {duration(month.balance_minutes, true)}
              </span>
            </p>
          </div>
          <div className="text-right text-sm">
            {request ? (
              <button type="button" className="text-right" onClick={() => onOpen(request.id)}>
                <RequestStatusBadge request={request} />
                <span className="mt-1 block text-stone-600">
                  {approved
                    ? splitText(request.approved_salary_cut_minutes ?? 0, request.approved_unpaid_work_minutes ?? 0)
                    : splitText(request.requested_salary_cut_minutes, request.requested_unpaid_work_minutes)}
                </span>
                {request.status === 'rejected' && request.reject_reason && (
                  <span className="block text-xs text-stone-500">“{request.reject_reason}”</span>
                )}
              </button>
            ) : state === 'create' ? (
              <div className="space-y-1">
                <Button onClick={onCreate}>{t('attendance.requests.create')}</Button>
                <p className="text-xs text-stone-500">
                  {t('attendance.requests.until', { date: formatDay(month.closes) })}
                </p>
              </div>
            ) : state === 'not_open' ? (
              <span className="text-stone-500">{t('attendance.requests.opensOn', { date: formatDay(month.opens, { day: 'numeric', month: 'short' }) })}</span>
            ) : state === 'no_request' ? (
              <Badge>{t('attendance.requests.status.no_request')}</Badge>
            ) : (
              <span className="text-stone-500">{t('attendance.requests.notNeeded')}</span>
            )}
          </div>
        </div>
      </Card>
    </li>
  )
}

// --- Reviewers -----------------------------------------------------------------------------------

type StatusFilter = RequestStatus | 'no_request' | ''

function useEmployeeOptions(enabled: boolean) {
  return useQuery({
    queryKey: ['attendance-requests-employees'],
    queryFn: async () =>
      (await api.get<Page<User>>('/users', { params: { page_size: 100 } })).data.items.filter((u) =>
        ['staff', 'supervisor'].includes(u.role),
      ),
    enabled,
    staleTime: 5 * 60_000,
  })
}

function ReviewList({ all, onOpen }: { all: boolean; onOpen(id: string): void }) {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const names = useCalendarNames()
  const now = currentYearMonth()
  const canListUsers = usePermission('users.view')
  const [status, setStatus] = useState<StatusFilter>('')
  const [year, setYear] = useState<number | null>(null)
  const [month, setMonth] = useState<number | null>(null)
  const [userId, setUserId] = useState('')
  const [page, setPage] = useState(1)
  const params: RequestListParams = all
    ? { status, year, month, userId, page }
    : { status: 'pending', year: null, month: null, userId: '', page }
  const list = useRequestList(params)
  const employees = useEmployeeOptions(all && canListUsers)
  const data = list.data
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1
  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v)
    setPage(1)
  }
  return (
    <div className="space-y-3">
      {all && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Field label={t('attendance.requests.filterStatus')}>
            {(id) => (
              <Select id={id} value={status} onChange={(e) => reset(setStatus)(e.target.value as StatusFilter)}>
                <option value="">{t('attendance.requests.allStatuses')}</option>
                {(['pending', 'approved', 'rejected', 'no_request'] as const).map((s) => (
                  <option key={s} value={s}>
                    {t(`attendance.requests.status.${s}`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t('attendance.mine.year')}>
            {(id) => (
              <Select
                id={id}
                value={year ?? ''}
                onChange={(e) => reset(setYear)(Number(e.target.value) || null)}
              >
                <option value="">{t('attendance.requests.allYears')}</option>
                {[now.year, now.year - 1, now.year - 2].map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t('attendance.mine.month')}>
            {(id) => (
              <Select
                id={id}
                value={month ?? ''}
                onChange={(e) => reset(setMonth)(Number(e.target.value) || null)}
              >
                <option value="">{t('attendance.requests.allMonths')}</option>
                {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                  <option key={m} value={m}>
                    {names.month(m)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          {canListUsers && (
            <Field label={t('attendance.requests.filterEmployee')}>
              {(id) => (
                <Select id={id} value={userId} onChange={(e) => reset(setUserId)(e.target.value)}>
                  <option value="">{t('attendance.requests.allEmployees')}</option>
                  {employees.data?.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          )}
        </div>
      )}
      {list.isError && <Alert tone="error">{errorMessage(list.error)}</Alert>}
      {list.isLoading ? (
        <div className="flex justify-center py-12 text-brand-600">
          <Spinner />
        </div>
      ) : !data?.items.length ? (
        <Card>
          <EmptyState>{t(all ? 'attendance.requests.emptyAll' : 'attendance.requests.emptyReview')}</EmptyState>
        </Card>
      ) : (
        <ul className="space-y-2">
          {data.items.map((row) => (
            <RequestItem key={row.id ?? `${row.user.id}-${row.year}-${row.month}`} row={row} onOpen={onOpen} />
          ))}
        </ul>
      )}
      {data && data.total > data.page_size && (
        <div className="flex items-center justify-between text-sm text-stone-600">
          <Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            ‹
          </Button>
          <span>{t('attendance.requests.page', { page, pages })}</span>
          <Button variant="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>
            ›
          </Button>
        </div>
      )}
    </div>
  )
}

function RequestItem({ row, onOpen }: { row: AttendanceRequestRow; onOpen(id: string): void }) {
  const { t } = useTranslation()
  const { me } = useAuth()
  const duration = useDuration()
  const splitText = useSplitText()
  const monthText = useMonthText()
  const formatDate = useFormatDate()
  const canViewAttendance = usePermission('attendance.view')
  const noRequest = row.status === 'no_request'
  const body = (
    <div className="flex flex-wrap items-start justify-between gap-2 text-left">
      <div className="min-w-0">
        <p className="font-medium text-stone-900">{row.user.full_name}</p>
        <p className="text-sm text-stone-600">
          {monthText(row.year, row.month)} · {t('attendance.requests.missing')} {duration(row.missing_minutes)}
        </p>
        {row.requested_salary_cut_minutes !== null && row.requested_unpaid_work_minutes !== null && (
          <p className="text-sm text-stone-700">
            {splitText(row.requested_salary_cut_minutes, row.requested_unpaid_work_minutes)}
          </p>
        )}
        {row.note && <p className="mt-1 truncate text-xs text-stone-500">“{row.note}”</p>}
      </div>
      <div className="text-right">
        {noRequest ? (
          <Badge>{t('attendance.requests.status.no_request')}</Badge>
        ) : (
          <RequestStatusBadge request={{ status: row.status as RequestStatus, approved_with_changes: row.approved_with_changes }} />
        )}
        {row.submitted_at && <p className="mt-1 text-xs text-stone-500">{formatDate(row.submitted_at)}</p>}
        {row.user.id === me?.user.id && <p className="text-xs text-stone-400">{t('attendance.requests.yours')}</p>}
      </div>
    </div>
  )
  return (
    <li>
      <div className="rounded-xl bg-white shadow-sm ring-1 ring-stone-200">
        {row.id ? (
          <button type="button" className="block w-full rounded-xl p-4 hover:bg-stone-50" onClick={() => onOpen(row.id as string)}>
            {body}
          </button>
        ) : canViewAttendance && row.user.id ? (
          <Link
            className="block rounded-xl p-4 hover:bg-stone-50"
            to={`${paths.attendanceEmployee(row.user.id)}?year=${row.year}&month=${row.month}`}
          >
            {body}
          </Link>
        ) : (
          <div className="p-4">{body}</div>
        )}
      </div>
    </li>
  )
}
