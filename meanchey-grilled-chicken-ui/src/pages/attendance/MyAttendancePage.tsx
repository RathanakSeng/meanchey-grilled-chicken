import { useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams, useSearchParams } from 'react-router-dom'
import { usePermission } from '@/auth/usePermission'
import { Icon } from '@/components/icons'
import { KpiGrid } from '@/components/KpiGrid'
import { Alert, Badge, Card, EmptyState, Field, PageHeader, Select, Spinner, cx } from '@/components/ui'
import { useIsMobileLayout } from '@/layouts/useIsMobileLayout'
import { useErrorMessage } from '@/lib/errors'
import { useCalendarNames } from '@/lib/format'
import { paths } from '@/lib/paths'
import type {
  AttendanceRecord,
  AttendanceSummary,
  AttendanceSummaryDay,
  AttendanceSummaryDayShift,
  DayOff,
  ShiftCode,
} from '@/lib/types'
import {
  businessToday,
  clockTime,
  statusTone,
  useAttendanceSummary,
  useAttendanceToday,
  useDayOffText,
  useDuration,
  useShiftName,
  type SummaryParams,
} from './api'
import { CheckButton, DayOffNotice, TrackingNotice } from './AttendanceCard'
import { FixSheet, type FixTarget } from './FixSheet'
import { RequestStrip } from './requests/RequestStrip'

/** My attendance (tracked employees): the check button, my KPIs and my days. */
export function MyAttendancePage() {
  const { t } = useTranslation()
  const today = useAttendanceToday()
  return (
    <AttendanceHistory
      who="me"
      header={(summary) => (
        <PageHeader
          title={t('attendance.mine.title')}
          subtitle={
            today.data?.workplace
              ? t('attendance.mine.workplace', {
                  name: today.data.workplace.name,
                  radius: today.data.workplace.radius_m,
                })
              : summary?.employee.workplace?.name
          }
          back={paths.attendance}
          actions={today.data && <CheckButton today={today.data} />}
        />
      )}
      notice={
        today.data && (today.data.starts_on || !today.data.tracked) ? (
          <TrackingNotice today={today.data} />
        ) : today.data?.day_off ? (
          <DayOffNotice today={today.data} />
        ) : null
      }
    />
  )
}

/** An employee's attendance for managers (attendance.view, in scope), opened from Today. With
 *  attendance.correct, a shift opens the Fix sheet. */
export function EmployeeAttendancePage() {
  const { t } = useTranslation()
  const { id = '' } = useParams()
  const canCorrect = usePermission('attendance.correct')
  return (
    <AttendanceHistory
      who={id}
      canCorrect={canCorrect}
      header={(summary) => {
        const e = summary?.employee
        return (
          <PageHeader
            title={e ? e.user.full_name : t('common.loading')}
            subtitle={
              e &&
              [
                t(`roles.${e.role}`),
                e.position,
                e.workplace?.name,
                e.is_active ? null : t('attendance.mine.inactive'),
              ]
                .filter(Boolean)
                .join(' · ')
            }
            back={paths.attendanceToday}
          />
        )
      }}
    />
  )
}

/** The period from the URL: `?year&month`; only a year → the whole year; nothing → this month. */
function usePeriod(): [SummaryParams, (next: SummaryParams) => void] {
  const [params, setParams] = useSearchParams()
  const [thisYear, thisMonth] = businessToday().split('-').map(Number)
  const year = Number(params.get('year')) || thisYear
  const month = params.get('year') ? Number(params.get('month')) || null : thisMonth
  const set = (next: SummaryParams) => {
    const p = new URLSearchParams(params)
    p.set('year', String(next.year))
    if (next.month) p.set('month', String(next.month))
    else p.delete('month')
    setParams(p, { replace: true })
  }
  return [{ year, month }, set]
}

function AttendanceHistory({
  who,
  header,
  notice,
  canCorrect = false,
}: {
  who: string
  header: (summary: AttendanceSummary | undefined) => ReactNode
  /** Shown under the header (today's day off on My attendance). */
  notice?: ReactNode
  canCorrect?: boolean
}) {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const [period, setPeriod] = usePeriod()
  const summary = useAttendanceSummary(who, period)
  const data = summary.data
  const [fix, setFix] = useState<FixTarget | null>(null)
  const openFix =
    canCorrect && data && !data.month_locked
      ? (date: string, s: AttendanceSummaryDayShift) =>
          setFix({ row: { user: data.employee.user }, shift: { code: s.code }, cell: { record: s.record }, date })
      : undefined

  return (
    <div className="mx-auto max-w-5xl">
      {header(data)}
      {notice && <div className="mb-4">{notice}</div>}
      <PeriodFilter period={period} since={data?.employee.since} onChange={setPeriod} />
      {summary.isError && <Alert tone="error">{errorMessage(summary.error)}</Alert>}
      {summary.isLoading ? (
        <div className="flex justify-center py-16 text-brand-600">
          <Spinner />
        </div>
      ) : data ? (
        <div className={cx('space-y-4', summary.isFetching && 'opacity-70')}>
          <Kpis summary={data} />
          <RequestStrip summary={data} mine={who === 'me'} />
          {data.days.length === 0 || !data.days.some((d) => d.shifts.some((s) => s.record)) ? (
            <Card>
              <EmptyState>{t('attendance.mine.empty')}</EmptyState>
            </Card>
          ) : data.period.month ? (
            <Card>
              {canCorrect && !data.month_locked && (
                <p className="mb-2 text-xs text-stone-500">{t('attendance.mine.fixHint')}</p>
              )}
              {canCorrect && data.month_locked && (
                <p className="mb-2 text-xs text-stone-500">🔒 {t('attendance.requests.lockedFixHint')}</p>
              )}
              <DayTable summary={data} days={data.days} onFix={openFix} />
            </Card>
          ) : (
            <YearByMonth summary={data} onFix={openFix} />
          )}
        </div>
      ) : null}
      {fix && data && <FixSheet target={fix} timezone={data.timezone} onClose={() => setFix(null)} />}
    </div>
  )
}

function PeriodFilter({
  period,
  since,
  onChange,
}: {
  period: SummaryParams
  since?: string
  onChange: (next: SummaryParams) => void
}) {
  const { t } = useTranslation()
  const names = useCalendarNames()
  const [thisYear, thisMonth] = businessToday().split('-').map(Number)
  const [sinceYear, sinceMonth] = since ? since.split('-').map(Number) : [thisYear, 1]
  const firstYear = Math.min(sinceYear, period.year)
  const years = Array.from({ length: thisYear - firstYear + 1 }, (_, i) => thisYear - i)
  // No future months, nor months before the account existed (the chosen one is always listed).
  const lastMonth = period.year === thisYear ? thisMonth : 12
  const firstMonth = Math.min(period.year === sinceYear ? sinceMonth : 1, period.month ?? 12)
  const months = Array.from({ length: Math.max(0, lastMonth - firstMonth + 1) }, (_, i) => firstMonth + i)
  return (
    <div className="mb-4 grid grid-cols-2 gap-2 sm:max-w-md">
      <Field label={t('attendance.mine.year')}>
        {(id) => (
          <Select
            id={id}
            value={period.year}
            onChange={(e) => {
              const year = Number(e.target.value)
              // A month later than today in the current year becomes the current month.
              const month = period.month && year === thisYear ? Math.min(period.month, thisMonth) : period.month
              onChange({ year, month })
            }}
          >
            {years.map((y) => (
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
            value={period.month ?? ''}
            onChange={(e) => onChange({ year: period.year, month: Number(e.target.value) || null })}
          >
            <option value="">{t('attendance.mine.wholeYear')}</option>
            {months.map((m) => (
              <option key={m} value={m}>
                {names.month(m)}
              </option>
            ))}
          </Select>
        )}
      </Field>
    </div>
  )
}

function Kpis({ summary }: { summary: AttendanceSummary }) {
  const { t } = useTranslation()
  const duration = useDuration()
  const k = summary.kpis
  const byShift = (counts: Partial<Record<ShiftCode, number>>) =>
    t('attendance.kpis.byShift', {
      morning: t('attendance.shiftsShort.morning'),
      m: counts.morning ?? 0,
      afternoon: t('attendance.shiftsShort.afternoon'),
      a: counts.afternoon ?? 0,
    })
  const balance = k.balance_minutes
  const chips = [
    k.early.count > 0 && t('attendance.kpis.early', { count: k.early.count, duration: duration(k.early.minutes) }),
    k.overtime.count > 0 &&
      t('attendance.kpis.overtime', { count: k.overtime.count, duration: duration(k.overtime.minutes) }),
    k.forgot_checkout > 0 && t('attendance.kpis.forgot', { count: k.forgot_checkout }),
  ].filter((c): c is string => Boolean(c))
  return (
    <div>
      <KpiGrid
        loading={false}
        items={[
          {
            key: 'present',
            label: t('attendance.kpis.present'),
            value: t('attendance.kpis.shifts', { count: k.present.total_shifts }),
            detail: (
              <>
                <span className="block text-stone-600">{duration(k.present.minutes)}</span>
                <span className="block text-[11px]">{byShift(k.present.by_shift)}</span>
              </>
            ),
            icon: 'check',
            tone: 'bg-green-50 text-green-700',
          },
          {
            key: 'absent',
            label: t('attendance.kpis.absent'),
            value: t('attendance.kpis.shifts', { count: k.absent.total_shifts }),
            detail: (
              <>
                <span className="block text-stone-600">{duration(k.absent.minutes)}</span>
                <span className="block text-[11px]">{byShift(k.absent.by_shift)}</span>
              </>
            ),
            icon: 'close',
            tone: 'bg-red-50 text-red-700',
          },
          {
            key: 'late',
            label: t('attendance.kpis.late'),
            value: t('attendance.kpis.times', { count: k.late.count }),
            detail: <span className="block text-stone-600">{duration(k.late.minutes)}</span>,
            icon: 'clock',
            tone: 'bg-amber-50 text-amber-700',
          },
          {
            key: 'balance',
            label: t('attendance.kpis.balance'),
            value: duration(balance, true),
            valueClassName: balance < 0 ? 'text-red-700' : balance > 0 ? 'text-green-700' : 'text-stone-900',
            detail: (
              <span className="block text-[11px]">
                {t('attendance.kpis.balanceDetail', {
                  extra: duration(k.extra_minutes, true),
                  missing: duration(-k.missing_minutes, true),
                })}
              </span>
            ),
            icon: 'scale',
            tone: 'bg-sky-50 text-sky-700',
          },
        ]}
      />
      {chips.length > 0 && (
        <div className="-mt-2 flex flex-wrap gap-2">
          {chips.map((c) => (
            <span key={c} className="rounded-full bg-stone-100 px-2.5 py-1 text-xs text-stone-600">
              {c}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

/** Per month of a whole year: collapsible, the newest month open; header with its counts. */
function YearByMonth({
  summary,
  onFix,
}: {
  summary: AttendanceSummary
  onFix?: (date: string, s: AttendanceSummaryDayShift) => void
}) {
  const { t } = useTranslation()
  const duration = useDuration()
  const names = useCalendarNames()
  const months = useMemo(() => {
    const out: { key: string; days: AttendanceSummaryDay[] }[] = []
    for (const d of summary.days) {
      const key = d.date.slice(0, 7)
      const last = out[out.length - 1]
      if (last?.key === key) last.days.push(d)
      else out.push({ key, days: [d] })
    }
    return out
  }, [summary.days])
  const [open, setOpen] = useState<Set<string>>(() => new Set(months[0] ? [months[0].key] : []))
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  return (
    <div className="space-y-2">
      {months.map(({ key, days }) => {
        const totals = monthTotals(days)
        const isOpen = open.has(key)
        return (
          <section key={key} className="rounded-xl bg-white shadow-sm ring-1 ring-stone-200">
            <button
              type="button"
              aria-expanded={isOpen}
              onClick={() => toggle(key)}
              className="flex w-full flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-3 text-left sm:px-5"
            >
              <span className="flex items-center gap-2 font-semibold text-stone-900">
                <Icon
                  name="chevronRight"
                  width={16}
                  height={16}
                  className={cx('text-stone-400 transition', isOpen && 'rotate-90')}
                />
                {names.monthYear(key)}
              </span>
              <span className="text-xs tabular-nums text-stone-500">
                {t('attendance.mine.monthLine', {
                  present: totals.present,
                  absent: totals.absent,
                  balance: duration(totals.balance, true),
                })}
              </span>
            </button>
            {isOpen && (
              <div className="border-t border-stone-100 p-4 sm:p-5">
                <DayTable summary={summary} days={days} onFix={onFix} />
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}

function scheduledMinutes(r: AttendanceRecord): number {
  return Math.round((Date.parse(r.scheduled_end) - Date.parse(r.scheduled_start)) / 60_000)
}

/** A month's present / absent counts and balance, the same way the API sums the period. */
function monthTotals(days: AttendanceSummaryDay[]) {
  let present = 0
  let absent = 0
  let balance = 0
  for (const d of days) {
    // Days off and untracked days don't count (like the API's KPIs).
    if (d.day_off || d.not_tracked) continue
    for (const { record: r } of d.shifts) {
      if (!r) continue
      if (r.status === 'absent') {
        absent += 1
        balance -= scheduledMinutes(r)
      } else {
        present += 1
        balance += r.early_minutes + r.overtime_minutes - r.late_minutes
      }
    }
  }
  return { present, absent, balance }
}

function DayTable({
  summary,
  days,
  onFix,
}: {
  summary: AttendanceSummary
  days: AttendanceSummaryDay[]
  onFix?: (date: string, s: AttendanceSummaryDayShift) => void
}) {
  const { t } = useTranslation()
  const isMobile = useIsMobileLayout()
  const names = useCalendarNames()
  const shiftName = useShiftName()
  const tz = summary.timezone
  const codes = summary.shifts.map((s) => s.code)
  const shiftOf = (d: AttendanceSummaryDay, code: ShiftCode) =>
    d.shifts.find((s) => s.code === code) ?? { code, status: 'none' as const, record: null }

  if (isMobile) {
    return (
      <ul className="-my-2 divide-y divide-stone-100">
        {days.map((d) => (
          <li key={d.date} className={cx('py-3', d.not_tracked && 'opacity-60')}>
            <p className="mb-1.5 flex flex-wrap items-center gap-2 text-sm font-semibold text-stone-800">
              {names.day(d.date)}
              {d.not_tracked ? <NotTrackedTag /> : d.day_off && <DayOffTag off={d.day_off} />}
            </p>
            {((!d.day_off && !d.not_tracked) || d.shifts.some((s) => s.record)) && (
              <div className="grid gap-1.5">
                {codes.map((code) => {
                  const s = shiftOf(d, code)
                  return (
                    <ShiftRowWrapper key={code} onClick={onFix && (() => onFix(d.date, s))}>
                      <span className="w-16 shrink-0 text-xs font-medium text-stone-600">
                        {t(`attendance.shiftsShort.${code}`)}
                      </span>
                      {s.status === 'absent' || s.status === 'none' ? (
                        <span className="flex-1 text-sm text-stone-400">—</span>
                      ) : (
                        <span className="flex flex-1 flex-wrap items-center gap-x-3 gap-y-0.5 text-sm">
                          <InTime record={s.record} timezone={tz} />
                          <OutTime record={s.record} timezone={tz} />
                        </span>
                      )}
                      <StatusCell shift={s} />
                    </ShiftRowWrapper>
                  )
                })}
              </div>
            )}
          </li>
        ))}
      </ul>
    )
  }

  const cell = 'px-3 py-2'
  return (
    <div className="-m-4 overflow-x-auto sm:-m-5">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-stone-500">
          <tr className="border-b border-stone-100">
            <th rowSpan={2} className={cx(cell, 'font-medium')}>
              {t('attendance.mine.date')}
            </th>
            {codes.map((code) => (
              <th key={code} colSpan={3} className={cx(cell, 'border-l border-stone-100 font-semibold text-stone-700')}>
                {shiftName(code)}
              </th>
            ))}
          </tr>
          <tr className="border-b border-stone-100">
            {codes.map((code) => (
              <FragmentHeaders key={code} />
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-stone-100">
          {days.map((d) => (
            <tr key={d.date} className={cx(d.not_tracked && 'bg-stone-50 text-stone-500')}>
              <td className={cx(cell, 'whitespace-nowrap font-medium text-stone-800')}>
                {names.day(d.date)}
              </td>
              {(d.day_off || d.not_tracked) && !d.shifts.some((s) => s.record) ? (
                <td colSpan={codes.length * 3} className={cx(cell, 'border-l border-stone-100 bg-stone-50')}>
                  {d.not_tracked ? <NotTrackedTag /> : d.day_off && <DayOffTag off={d.day_off} />}
                </td>
              ) : codes.map((code) => {
                const s = shiftOf(d, code)
                const fix = onFix && (() => onFix(d.date, s))
                const empty = s.status === 'absent' || s.status === 'none'
                return (
                  <FixableCells key={code} onClick={fix} cell={cell}>
                    {empty ? <span className="text-stone-400">—</span> : <InTime record={s.record} timezone={tz} />}
                    {empty ? <span className="text-stone-400">—</span> : <OutTime record={s.record} timezone={tz} />}
                    <StatusCell shift={s} />
                  </FixableCells>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** "Not tracked": a day inside a supervisor's switched-off period (greyed, in no KPI). */
function NotTrackedTag() {
  const { t } = useTranslation()
  return (
    <span className="rounded bg-stone-200 px-1.5 py-0.5 text-xs font-medium text-stone-700">
      {t('attendance.tracking.notTracked')}
    </span>
  )
}

/** "Holiday: Pchum Ben" / "Day off" in a day row (those days don't count in the KPIs). */
function DayOffTag({ off }: { off: DayOff }) {
  const dayOffText = useDayOffText()
  return (
    <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-950 ring-1 ring-inset ring-amber-300">
      {dayOffText(off)}
    </span>
  )
}

function FragmentHeaders() {
  const { t } = useTranslation()
  return (
    <>
      <th className="border-l border-stone-100 px-3 py-1.5 font-medium">{t('attendance.mine.in')}</th>
      <th className="px-3 py-1.5 font-medium">{t('attendance.mine.out')}</th>
      <th className="px-3 py-1.5 font-medium">{t('attendance.mine.status')}</th>
    </>
  )
}

/** A shift's three cells; with Fix, each opens the sheet (one button per row of cells would
 *  not be valid table markup). */
function FixableCells({
  children,
  onClick,
  cell,
}: {
  children: [ReactNode, ReactNode, ReactNode]
  onClick?: () => void
  cell: string
}) {
  return (
    <>
      {children.map((content, i) => (
        <td
          key={i}
          className={cx(cell, 'whitespace-nowrap', i === 0 && 'border-l border-stone-100', onClick && 'cursor-pointer hover:bg-stone-50')}
          onClick={onClick}
        >
          {i === 2 && onClick ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onClick()
              }}
              className="rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500">
              {content}
            </button>
          ) : (
            content
          )}
        </td>
      ))}
    </>
  )
}

function ShiftRowWrapper({ children, onClick }: { children: ReactNode; onClick?: () => void }) {
  const className = 'flex w-full items-center gap-2 rounded-lg bg-stone-50 px-2 py-1.5 text-left'
  return onClick ? (
    <button type="button" onClick={onClick} className={cx(className, 'hover:bg-stone-100')}>
      {children}
    </button>
  ) : (
    <div className={className}>{children}</div>
  )
}

function Tag({ tone, title, children }: { tone: 'red' | 'green'; title: string; children: ReactNode }) {
  return (
    <span
      title={title}
      aria-label={title}
      className={cx(
        'ml-1 rounded px-1 text-[11px] font-medium',
        tone === 'red' ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700',
      )}
    >
      {children}
    </span>
  )
}

function InTime({ record: r, timezone }: { record: AttendanceRecord | null; timezone: string }) {
  const { t } = useTranslation()
  if (!r?.check_in_at) return <span className="text-stone-400">—</span>
  return (
    <span className="tabular-nums text-stone-900">
      {clockTime(r.check_in_at, timezone)}
      {r.late_minutes > 0 ? (
        <Tag tone="red" title={t('attendance.tags.lateTitle', { count: r.late_minutes })}>
          {t('attendance.tags.late', { count: r.late_minutes })}
        </Tag>
      ) : r.early_minutes > 0 ? (
        <Tag tone="green" title={t('attendance.tags.earlyTitle', { count: r.early_minutes })}>
          {t('attendance.tags.early', { count: r.early_minutes })}
        </Tag>
      ) : null}
    </span>
  )
}

function OutTime({ record: r, timezone }: { record: AttendanceRecord | null; timezone: string }) {
  const { t } = useTranslation()
  if (r?.checkout_status === 'forgot_checkout') {
    return <span className="text-xs font-medium text-amber-700">{t('attendance.status.forgot_checkout')}</span>
  }
  if (!r?.check_out_at) return <span className="text-stone-400">—</span>
  return (
    <span className="tabular-nums text-stone-900">
      {clockTime(r.check_out_at, timezone)}
      {r.overtime_minutes > 0 && (
        <Tag tone="green" title={t('attendance.tags.overtimeTitle', { count: r.overtime_minutes })}>
          {t('attendance.tags.overtime', { count: r.overtime_minutes })}
        </Tag>
      )}
    </span>
  )
}

function StatusCell({ shift: s }: { shift: AttendanceSummaryDayShift }) {
  const { t } = useTranslation()
  const r = s.record
  if (!r) return <span className="text-stone-400">{t('attendance.mine.noRecord')}</span>
  return (
    <span className="inline-flex items-center gap-1">
      <Badge tone={statusTone(r)}>{t(`attendance.status.${r.status}`)}</Badge>
      {r.corrected && (
        <span
          title={t('attendance.mine.correctedTip', { reason: r.correction_reason ?? '' })}
          className="text-[11px] italic text-sky-700 underline decoration-dotted"
        >
          {t('attendance.tags.corrected')}
        </span>
      )}
    </span>
  )
}
