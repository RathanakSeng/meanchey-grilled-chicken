import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { usePermission } from '@/auth/usePermission'
import { Icon } from '@/components/icons'
import { Alert, Badge, Button, Card, EmptyState, Field, Input, PageHeader, Select, cx } from '@/components/ui'
import { useIsMobileLayout } from '@/layouts/useIsMobileLayout'
import { useErrorMessage } from '@/lib/errors'
import { initials, useFormatDay } from '@/lib/format'
import { paths } from '@/lib/paths'
import type { AttendanceDay, AttendanceDayCell, AttendanceDayRow, AttendanceDayShift } from '@/lib/types'
import {
  businessToday,
  clockTime,
  statusTone,
  useAttendanceDay,
  useDayOffText,
  useShiftName,
  useStatusText,
} from './api'
import { FixSheet, type FixTarget } from './FixSheet'
import { addDays } from './scheduling/shared'

type StatusFilter = '' | 'present' | 'late' | 'absent' | 'not_yet' | 'no_record' | 'forgot_checkout'
type RoleFilter = '' | 'staff' | 'supervisor'

function cellMatches(cell: AttendanceDayCell | undefined, status: StatusFilter): boolean {
  if (!status) return true
  if (!cell) return false
  if (status === 'not_yet' || status === 'no_record') return cell.state === status
  if (status === 'forgot_checkout') return cell.record?.checkout_status === 'forgot_checkout'
  return cell.record?.status === status
}

/** The row's shift at its own workplace (each workplace has its schedule), else the headline one. */
function rowShift(day: AttendanceDay, row: AttendanceDayRow, shift: AttendanceDayShift): AttendanceDayShift {
  const own = day.workplaces.find((w) => w.id === row.workplace?.id)
  return own?.shifts.find((s) => s.code === shift.code) ?? shift
}

/** 0 = absent / no record, 1 = late or forgot check-out, 2 = not yet, 3 = all fine: exceptions first. */
function severity(row: AttendanceDayRow): number {
  let worst = 3
  for (const c of Object.values(row.shifts)) {
    if (!c) continue
    const r = c.record
    const v =
      c.state === 'no_record' || r?.status === 'absent'
        ? 0
        : r?.status === 'late' || r?.checkout_status === 'forgot_checkout'
          ? 1
          : c.state === 'not_yet'
            ? 2
            : 3
    worst = Math.min(worst, v)
  }
  return worst
}

/** Today (attendance.view): a summary per shift (and per workplace) and one row per employee in
 *  scope, exceptions first (the name opens their attendance history); Fix with attendance.correct;
 *  Export CSV of what the filters show. Filters live in the URL (?date&workplace&status&role&q). */
export function TodayPage() {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const isMobile = useIsMobileLayout()
  const canCorrect = usePermission('attendance.correct')
  const formatDay = useFormatDay()
  const shiftName = useShiftName()
  const statusText = useStatusText()
  const [params, setParams] = useSearchParams()
  const today = businessToday()
  const date = params.get('date') || today
  const status = (params.get('status') ?? '') as StatusFilter
  const role = (params.get('role') ?? '') as RoleFilter
  const q = params.get('q') ?? ''
  const workplaceId = params.get('workplace') ?? ''
  const day = useAttendanceDay({ date, workplaceId })
  const dayOffText = useDayOffText()
  const [fix, setFix] = useState<FixTarget | null>(null)

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }
  const setDate = (value: string) => set('date', value === today ? '' : value)
  const filtered = Boolean(status || role || q || workplaceId)

  const matches = (r: AttendanceDayRow) => {
    const needle = q.trim().toLowerCase()
    return (
      (!role || r.role === role) &&
      (!needle ||
        r.user.full_name.toLowerCase().includes(needle) ||
        (r.position ?? '').toLowerCase().includes(needle) ||
        (r.user.telegram_username ?? '').includes(needle))
    )
  }
  const rows = useMemo(() => {
    const list = (day.data?.rows ?? []).filter(
      (r) => matches(r) && (!status || Object.values(r.shifts).some((c) => cellMatches(c, status))),
    )
    return list
      .map((r, i) => ({ r, i, s: severity(r) }))
      .sort((a, b) => a.s - b.s || a.i - b.i)
      .map((x) => x.r)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [day.data, q, role, status])

  const shifts = day.data?.shifts ?? []
  const tz = day.data?.timezone
  const options = day.data?.workplace_options ?? []
  const several = options.length > 1 || (day.data?.workplaces.length ?? 0) > 1
  const fixFor = (row: AttendanceDayRow, s: AttendanceDayShift) =>
    canCorrect && day.data
      ? () => setFix({ row, shift: rowShift(day.data!, row, s), cell: row.shifts[s.code], date })
      : undefined

  /** The rows on screen as a spreadsheet file (BOM so Excel reads Khmer). */
  const exportCsv = () => {
    if (!day.data) return
    const cols = [
      t('attendance.today.employee'),
      t('attendance.today.role'),
      t('userForm.position'),
      t('attendance.today.workplace'),
      ...shifts.flatMap((s) => [
        `${shiftName(s.code)} · ${t('attendance.today.status')}`,
        `${shiftName(s.code)} · ${t('attendance.today.csvIn')}`,
        `${shiftName(s.code)} · ${t('attendance.today.csvOut')}`,
      ]),
    ]
    const cell = (v: string) => `"${v.replace(/"/g, '""')}"`
    const lines = [cols, ...rows.map((row) => [
      row.user.full_name,
      t(`roles.${row.role}`),
      row.position ?? '',
      row.workplace?.name ?? '',
      ...shifts.flatMap((s) => {
        const c = row.shifts[s.code]
        const r = c?.record
        return [
          r ? statusText(r) : t(`attendance.state.${c?.state ?? 'not_yet'}`),
          clockTime(r?.check_in_at, tz),
          r?.checkout_status === 'forgot_checkout'
            ? t('attendance.status.forgot_checkout')
            : clockTime(r?.check_out_at, tz),
        ]
      }),
    ])]
    const blob = new Blob(['﻿' + lines.map((l) => l.map(cell).join(',')).join('\r\n')], {
      type: 'text/csv;charset=utf-8',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `attendance-${date}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <>
      <PageHeader
        title={t('attendance.today.title')}
        back={paths.attendance}
        subtitle={
          <>
            {formatDay(date, { dateStyle: 'full' })}
            {date === today && <span className="font-semibold text-brand-700"> · {t('attendance.today.todayTag')}</span>}
          </>
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center rounded-lg bg-white ring-1 ring-inset ring-stone-300">
              <button
                type="button"
                onClick={() => setDate(addDays(date, -1))}
                className="rounded-l-lg p-2 text-stone-600 hover:bg-stone-50"
                aria-label={t('attendance.today.previousDay')}
              >
                <Icon name="chevronLeft" width={18} height={18} />
              </button>
              <input
                type="date"
                value={date}
                max={today}
                onChange={(e) => e.target.value && setDate(e.target.value)}
                aria-label={t('attendance.today.date')}
                className="border-x border-stone-200 bg-transparent px-2 py-1.5 text-sm text-stone-800 focus:outline-none"
              />
              <button
                type="button"
                disabled={date >= today}
                onClick={() => setDate(addDays(date, 1))}
                className="rounded-r-lg p-2 text-stone-600 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-40"
                aria-label={t('attendance.today.nextDay')}
              >
                <Icon name="chevronRight" width={18} height={18} />
              </button>
            </div>
            <Button variant="secondary" disabled={date === today} onClick={() => setDate(today)}>
              {t('attendance.today.todayButton')}
            </Button>
            <Button onClick={exportCsv} disabled={!day.data || rows.length === 0}>
              <Icon name="download" width={16} height={16} />
              {t('attendance.today.export')}
            </Button>
          </div>
        }
      />

      <Card className="mb-4">
        <div className="grid items-end gap-3 sm:grid-cols-2 lg:grid-cols-[repeat(3,minmax(0,1fr))_minmax(0,1.4fr)_auto]">
          {several && (
            <Field label={t('attendance.today.workplace')}>
              {(id) => (
                <Select id={id} value={workplaceId} onChange={(e) => set('workplace', e.target.value)}>
                  <option value="">{t('attendance.today.allWorkplaces')}</option>
                  {options.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          )}
          <Field label={t('attendance.today.status')}>
            {(id) => (
              <Select id={id} value={status} onChange={(e) => set('status', e.target.value)}>
                <option value="">{t('attendance.today.allStatuses')}</option>
                {(['present', 'late', 'absent', 'not_yet', 'no_record', 'forgot_checkout'] as const).map((s) => (
                  <option key={s} value={s}>
                    {t(`attendance.filter.${s}`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t('attendance.today.role')}>
            {(id) => (
              <Select id={id} value={role} onChange={(e) => set('role', e.target.value)}>
                <option value="">{t('attendance.today.allRoles')}</option>
                <option value="staff">{t('roles.staff')}</option>
                <option value="supervisor">{t('roles.supervisor')}</option>
              </Select>
            )}
          </Field>
          <Field label={t('attendance.today.search')}>
            {(id) => (
              <div className="relative">
                <Icon
                  name="search"
                  width={16}
                  height={16}
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-400"
                />
                <Input
                  id={id}
                  type="search"
                  className="pl-9"
                  placeholder={t('attendance.today.searchPlaceholder')}
                  value={q}
                  onChange={(e) => set('q', e.target.value)}
                />
              </div>
            )}
          </Field>
          <Button
            variant="ghost"
            disabled={!filtered}
            onClick={() => setParams(date === today ? {} : { date }, { replace: true })}
          >
            {t('attendance.today.reset')}
          </Button>
        </div>
      </Card>

      {day.isError && <Alert tone="error">{errorMessage(day.error)}</Alert>}
      {day.data?.day_off && (
        <Alert tone="warning" className="mb-4">
          {t('attendance.today.dayOff', {
            what: dayOffText(day.data.day_off),
            name: headlineName(day.data),
          })}
        </Alert>
      )}

      <ShiftSummary
        shifts={shifts}
        loading={day.isLoading}
        timezone={tz}
        several={several && !workplaceId}
        status={status}
        onFilter={(s) => set('status', status === s ? '' : s)}
      />
      {day.data && !workplaceId && day.data.workplaces.length > 1 && (
        <WorkplaceBreakdown day={day.data} onPick={(id) => set('workplace', id)} />
      )}

      <Card
        title={
          <span className="flex flex-wrap items-baseline gap-x-2">
            {t('attendance.today.employees')}
            <span className="text-xs font-normal text-stone-500">
              {t('attendance.today.peopleCount', { count: rows.length })}
            </span>
          </span>
        }
        className={cx('mb-4', day.isFetching && !day.isLoading && 'opacity-70')}
      >
        {rows.length === 0 ? (
          <EmptyState>{day.isLoading ? t('common.loading') : t('attendance.today.empty')}</EmptyState>
        ) : isMobile ? (
          <ul className="-my-2 divide-y divide-stone-100">
            {rows.map((row) => (
              <li key={row.user.id ?? row.user.full_name} className="py-3">
                <EmployeeName row={row} showWorkplace={several && !workplaceId} />
                <div className="mt-2 grid gap-2">
                  {shifts.map((s) => (
                    <div key={s.code} className="rounded-lg bg-stone-50 p-2">
                      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-stone-500">
                        {shiftName(s.code)}
                      </p>
                      <CellView
                        cell={row.shifts[s.code]}
                        shift={rowShift(day.data!, row, s)}
                        timezone={tz}
                        onFix={fixFor(row, s)}
                      />
                    </div>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="-m-4 overflow-x-auto sm:-m-5">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-stone-100 text-xs uppercase tracking-wide text-stone-500">
                <tr>
                  <th className="px-5 py-2.5 font-medium">{t('attendance.today.employee')}</th>
                  {shifts.map((s) => (
                    <th key={s.code} className="px-4 py-2.5 font-medium">
                      {shiftName(s.code)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {rows.map((row) => (
                  <tr key={row.user.id ?? row.user.full_name} className="align-top hover:bg-stone-50/60">
                    <td className="px-5 py-3.5">
                      <EmployeeName row={row} showWorkplace={several && !workplaceId} avatar />
                    </td>
                    {shifts.map((s) => (
                      <td key={s.code} className="px-4 py-3.5">
                        <CellView
                          cell={row.shifts[s.code]}
                          shift={rowShift(day.data!, row, s)}
                          timezone={tz}
                          onFix={fixFor(row, s)}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {/* Not expected that day and in no KPI: attendance starts later / switched off. */}
      {day.data && (
        <>
          <TrackingGroup
            title={t('attendance.tracking.startsLater')}
            hint={t('attendance.tracking.startsLaterHint')}
            rows={day.data.starts_later.filter((r) => matches(r))}
            several={several && !workplaceId}
            later
          />
          <TrackingGroup
            title={t('attendance.tracking.notTrackedGroup')}
            hint={t('attendance.tracking.notTrackedHint')}
            rows={day.data.not_tracked.filter((r) => matches(r))}
            several={several && !workplaceId}
          />
        </>
      )}
      {fix && tz && <FixSheet target={fix} timezone={tz} onClose={() => setFix(null)} />}
    </>
  )
}

/** The workplace whose day the headline shows: the filtered one, else the default. */
function headlineName(day: AttendanceDay): string {
  const id = day.workplace_id ?? day.workplaces.find((w) => w.is_default)?.id
  return day.workplaces.find((w) => w.id === id)?.name ?? ''
}

const CHIP_TONES = {
  present: 'bg-green-50 text-green-800 ring-green-200',
  late: 'bg-amber-50 text-amber-800 ring-amber-200',
  absent: 'bg-red-50 text-red-800 ring-red-200',
} as const

/** A count of one status; zero is dashed and quiet. Clicking applies the status filter. */
function CountChip({
  kind,
  count,
  selected,
  onClick,
}: {
  kind: keyof typeof CHIP_TONES
  count: number
  selected: boolean
  onClick(): void
}) {
  const { t } = useTranslation()
  const icon = kind === 'present' ? 'check' : kind === 'late' ? 'clock' : 'close'
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={cx(
        'inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium ring-1 ring-inset transition',
        count > 0 ? CHIP_TONES[kind] : 'border border-dashed border-stone-300 bg-white text-stone-400 ring-0',
        selected && 'ring-2 ring-brand-500',
      )}
    >
      <Icon name={icon} width={14} height={14} />
      <span className="font-semibold tabular-nums">{count}</span>
      {t(`attendance.kpi.${kind}`)}
    </button>
  )
}

/** One row per shift: times, a bar of who came / was late / was absent, and the counts. */
function ShiftSummary({
  shifts,
  loading,
  timezone,
  several,
  status,
  onFilter,
}: {
  shifts: AttendanceDayShift[]
  loading: boolean
  timezone?: string
  several: boolean
  status: StatusFilter
  onFilter(status: StatusFilter): void
}) {
  const { t } = useTranslation()
  const shiftName = useShiftName()
  return (
    <Card
      title={t('attendance.today.shiftSummary')}
      actions={
        <span className="hidden text-xs text-stone-500 sm:block">
          {several && `${t('attendance.today.shiftsVary')} · `}
          {t('attendance.today.clickToFilter')}
        </span>
      }
      className="mb-4"
    >
      {loading && shifts.length === 0 ? (
        <div className="h-16 animate-pulse rounded-lg bg-stone-100" />
      ) : (
        <ul className="-my-3 divide-y divide-stone-100">
          {shifts.map((shift) => {
            const k = shift.kpis
            const absent = k.absent + k.no_record
            const attended = k.present + k.late
            const pct = (n: number) => (k.expected ? `${(n / k.expected) * 100}%` : '0%')
            return (
              <li key={shift.code} className="grid items-center gap-3 py-4 lg:grid-cols-[14rem_minmax(0,1fr)_auto] lg:gap-6">
                <div>
                  <p className="flex flex-wrap items-center gap-2 font-semibold text-stone-900">
                    {shiftName(shift.code)}
                    <Badge>{t(`attendance.phase.${shift.phase}`)}</Badge>
                  </p>
                  <p className="text-xs text-stone-500">
                    <span className="tabular-nums">
                      {clockTime(shift.start, timezone)}–{clockTime(shift.end, timezone)}
                    </span>
                    {' · '}
                    {t('attendance.today.expectedOut', { expected: k.expected, out: k.checked_out })}
                    {k.forgot_checkout > 0 && ` · ${t('attendance.today.forgotCount', { count: k.forgot_checkout })}`}
                  </p>
                </div>
                <div>
                  <div className="flex h-2.5 overflow-hidden rounded-full bg-stone-100">
                    <span className="bg-green-600" style={{ width: pct(k.present) }} />
                    <span className="bg-amber-500" style={{ width: pct(k.late) }} />
                    <span className="bg-red-600" style={{ width: pct(absent) }} />
                  </div>
                  <p className="mt-1 text-xs text-stone-500">
                    {t('attendance.today.attended', { done: attended, expected: k.expected })}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <CountChip kind="present" count={k.present} selected={status === 'present'} onClick={() => onFilter('present')} />
                  <CountChip kind="late" count={k.late} selected={status === 'late'} onClick={() => onFilter('late')} />
                  <CountChip kind="absent" count={absent} selected={status === 'absent'} onClick={() => onFilter('absent')} />
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

/** Each workplace with its own shift times and counts; tapping one filters the list. */
function WorkplaceBreakdown({ day, onPick }: { day: AttendanceDay; onPick: (id: string) => void }) {
  const { t } = useTranslation()
  const shiftName = useShiftName()
  const dayOffText = useDayOffText()
  const codes = day.shifts.map((s) => s.code)
  return (
    <Card title={t('attendance.today.byWorkplace')} className="mb-4">
      <div className="-m-4 overflow-x-auto sm:-m-5">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-stone-100 text-xs uppercase tracking-wide text-stone-500">
            <tr>
              <th className="px-5 py-2.5 font-medium">{t('attendance.today.workplace')}</th>
              {codes.map((c) => (
                <th key={c} className="px-4 py-2.5 font-medium">
                  {shiftName(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {day.workplaces.map((w) => (
              <tr key={w.id} onClick={() => onPick(w.id)} className="cursor-pointer hover:bg-stone-50">
                <td className="px-5 py-3 font-semibold text-stone-900">{w.name}</td>
                {w.day_off ? (
                  <td colSpan={codes.length} className="px-4 py-3 text-xs font-medium text-amber-900">
                    {dayOffText(w.day_off)}
                  </td>
                ) : (
                  codes.map((code) => {
                    const s = w.shifts.find((x) => x.code === code)
                    if (!s) return <td key={code} />
                    const absent = s.kpis.absent + s.kpis.no_record
                    const [tone, label, n] =
                      absent > 0
                        ? (['red', 'absent', absent] as const)
                        : s.kpis.late > 0
                          ? (['amber', 'late', s.kpis.late] as const)
                          : (['green', 'present', s.kpis.present] as const)
                    return (
                      <td key={code} className="px-4 py-3">
                        <span className="inline-flex flex-wrap items-center gap-2">
                          <span className="text-xs tabular-nums text-stone-600">
                            {clockTime(s.start, day.timezone)}–{clockTime(s.end, day.timezone)}
                          </span>
                          {s.kpis.expected > 0 && (
                            <>
                              <Badge tone={tone}>{t(`attendance.today.chip.${label}`, { count: n })}</Badge>
                              <span className="text-xs text-stone-500">
                                {t('attendance.today.ofExpected', { expected: s.kpis.expected })}
                              </span>
                            </>
                          )}
                        </span>
                      </td>
                    )
                  })
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

/** A small group under the list: employees not expected that day ("Starts later" with their
 *  dates, "Not tracked"). */
function TrackingGroup({
  title,
  hint,
  rows,
  several,
  later,
}: {
  title: string
  hint: string
  rows: AttendanceDayRow[]
  several: boolean
  later?: boolean
}) {
  const { t } = useTranslation()
  const formatDay = useFormatDay()
  if (rows.length === 0) return null
  return (
    <section className="mb-4">
      <h2 className="text-sm font-semibold text-stone-700">
        {title} <span className="font-normal text-stone-500">({rows.length})</span>
      </h2>
      <p className="mb-2 text-xs text-stone-500">{hint}</p>
      <Card>
        <ul className="-my-2 divide-y divide-stone-100">
          {rows.map((row) => (
            <li key={row.user.id ?? row.user.full_name} className="flex items-center justify-between gap-2 py-2">
              <EmployeeName row={row} showWorkplace={several} />
              {later && row.starts_on ? (
                <Badge tone="blue">{t('attendance.tracking.startsLaterOn', { date: formatDay(row.starts_on) })}</Badge>
              ) : (
                <Badge>{t('attendance.tracking.notTracked')}</Badge>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </section>
  )
}

function EmployeeName({
  row,
  showWorkplace,
  avatar,
}: {
  row: AttendanceDayRow
  showWorkplace?: boolean
  avatar?: boolean
}) {
  const { t } = useTranslation()
  const name = row.user.full_name
  return (
    <div className="flex min-w-0 items-center gap-3">
      {avatar && (
        <span
          aria-hidden="true"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-50 text-sm font-semibold text-brand-700"
        >
          {initials(name)}
        </span>
      )}
      <div className="min-w-0">
        {row.user.id ? (
          <Link
            to={paths.attendanceEmployee(row.user.id)}
            className={cx(
              'inline-flex items-center gap-1 font-semibold text-stone-900 hover:text-brand-700 hover:underline',
              !row.is_active && 'text-stone-500',
            )}
          >
            {name}
          </Link>
        ) : (
          <p className={cx('font-semibold text-stone-900', !row.is_active && 'text-stone-500')}>{name}</p>
        )}
        <p className="text-xs text-stone-500">
          {t(`roles.${row.role}`)}
          {row.position ? ` · ${row.position}` : ''}
          {showWorkplace && row.workplace ? ` · ${row.workplace.name}` : ''}
          {!row.is_active && ` · ${t('status.inactive')}`}
        </p>
      </div>
    </div>
  )
}

function CellView({
  cell,
  shift,
  timezone,
  onFix,
}: {
  cell?: AttendanceDayCell
  shift: AttendanceDayShift
  timezone?: string
  onFix?: () => void
}) {
  const { t } = useTranslation()
  const statusText = useStatusText()
  const r = cell?.record
  return (
    <div className="flex min-w-0 flex-col items-start gap-1">
      <div className="flex flex-wrap items-center gap-1.5">
        {r ? (
          <Badge tone={statusTone(r)}>
            <Icon name={r.status === 'present' ? 'check' : r.status === 'late' ? 'clock' : 'close'} width={12} height={12} />
            {statusText(r)}
          </Badge>
        ) : (
          <Badge tone={cell?.state === 'no_record' ? 'red' : 'neutral'}>
            {cell?.state === 'no_record' && <Icon name="close" width={12} height={12} />}
            {t(`attendance.state.${cell?.state ?? 'not_yet'}`)}
          </Badge>
        )}
        {r?.corrected && (
          <span title={r.correction_reason ?? ''}>
            <Badge tone="blue">
              <Icon name="pencil" width={11} height={11} />
              {t('attendance.correctedShort')}
            </Badge>
          </span>
        )}
      </div>
      <p className="text-xs tabular-nums text-stone-500">
        {t('attendance.today.scheduled', {
          from: clockTime(shift.start, timezone),
          to: clockTime(shift.end, timezone),
        })}
      </p>
      {r?.check_in_at ? (
        <p className="text-xs tabular-nums text-stone-800">
          {t('attendance.inOut', {
            in: clockTime(r.check_in_at, timezone),
            out:
              r.checkout_status === 'forgot_checkout'
                ? t('attendance.status.forgot_checkout')
                : clockTime(r.check_out_at, timezone),
          })}
          {r.check_in_distance_m !== null && ` · ${t('attendance.distance', { distance: Math.round(r.check_in_distance_m) })}`}
        </p>
      ) : (
        cell?.state !== 'day_off' && <p className="text-xs text-stone-500">{t('attendance.today.noCheckIn')}</p>
      )}
      {onFix && (
        <button
          type="button"
          onClick={onFix}
          className="inline-flex items-center gap-1 text-xs font-semibold text-brand-700 hover:underline"
        >
          <Icon name={r ? 'pencil' : 'plus'} width={12} height={12} />
          {r ? t('attendance.fix.fix') : t('attendance.fix.add')}
        </button>
      )}
    </div>
  )
}
