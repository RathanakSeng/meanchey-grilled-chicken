import { useQuery, type QueryClient } from '@tanstack/react-query'
import { useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '@/auth/AuthProvider'
import { api } from '@/lib/api'
import { useLocalized } from '@/lib/format'
import { TRACKED_ROLES } from '@/lib/roles'
import type {
  AttendanceCalendar,
  AttendanceDay,
  AttendanceRecord,
  AttendanceSummary,
  AttendanceToday,
  DayOff,
  Holiday,
  Scheduling,
  ShiftCode,
  Workplace,
  WorkplaceOption,
} from '@/lib/types'

/** `month` null: the whole year. */
export interface SummaryParams {
  year: number
  month: number | null
}

export interface DayParams {
  date: string
  workplaceId: string
}

/** Query keys (see docs/ARCHITECTURE.md). */
export const attendanceKeys = {
  meToday: ['attendance-me-today'] as const,
  day: (params: DayParams) => ['attendance-day', params] as const,
  dayAll: ['attendance-day'] as const,
  workplaces: (params: { includeArchived: boolean }) => ['attendance-workplaces', params] as const,
  workplacesAll: ['attendance-workplaces'] as const,
  workplace: (id: string) => ['attendance-workplace', id] as const,
  workplaceAll: ['attendance-workplace'] as const,
  workplaceOptions: ['attendance-workplace-options'] as const,
  /** `who`: 'me' or the employee's id. */
  summary: (who: string, params: SummaryParams) => ['attendance-summary', who, params] as const,
  summaryAll: ['attendance-summary'] as const,
  /** `workplaceIds` empty: all workplaces. */
  scheduling: (params: { workplaceIds: string[] }) => ['attendance-scheduling', params] as const,
  schedulingAll: ['attendance-scheduling'] as const,
  calendar: (params: { year: number; month: number; workplaceIds: string[] }) =>
    ['attendance-calendar', params] as const,
  calendarAll: ['attendance-calendar'] as const,
  holidays: (params: { year: number }) => ['attendance-holidays', params] as const,
  holidaysAll: ['attendance-holidays'] as const,
}

/** The business time zone (the API sends it; Cambodia has no DST). */
export const BUSINESS_TZ = 'Asia/Phnom_Penh'

/** Staff and supervisors have attendance (also a supervisor switched off, for past records);
 *  others never call `me/today`. */
export function useHasAttendance(): boolean {
  const { me } = useAuth()
  return Boolean(me && me.user.is_active && TRACKED_ROLES.includes(me.user.role))
}

/** Staff and supervisors who aren't switched off: they get the Attendance card and check in. */
export function useIsTracked(): boolean {
  const { me } = useAuth()
  return useHasAttendance() && me?.user.attendance_tracked !== false
}

// Refetch this long after a window opens / closes, so the server is surely past it.
const SWITCH_DELAY_MS = 1_000

/**
 * Today's state and the one next action. Refetched every minute and on focus while a screen
 * that shows it is open, and **exactly** when the next window opens (`next_opens_at`) or the
 * open one closes (`closes_at`), so the check buttons switch on and off on time.
 */
export function useAttendanceToday(enabled = true) {
  const tracked = useHasAttendance()
  const query = useQuery({
    queryKey: attendanceKeys.meToday,
    queryFn: async () => (await api.get<AttendanceToday>('/attendance/me/today')).data,
    enabled: enabled && tracked,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    staleTime: 15_000,
  })
  const { data, dataUpdatedAt, refetch } = query
  useEffect(() => {
    if (!data) return
    const na = data.next_action
    const at = na.action === 'none' ? na.next_opens_at : na.closes_at
    if (!at) return
    // Server instants on the device's clock: shift by how far the device is from the server.
    const skew = Date.parse(data.server_time) - dataUpdatedAt
    const wait = Date.parse(at) - skew - Date.now() + SWITCH_DELAY_MS
    // Far-off times (tomorrow) are left to the minute refetch; setTimeout caps at ~24.8 days.
    if (wait < 0 || wait > 12 * 60 * 60 * 1000) return
    const timer = window.setTimeout(() => void refetch(), wait)
    return () => window.clearTimeout(timer)
  }, [data, dataUpdatedAt, refetch])
  return query
}

/** The business date (YYYY-MM-DD) of an instant. */
export function businessDate(iso: string, timeZone = BUSINESS_TZ): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone }).format(new Date(iso))
}

export function useAttendanceDay(params: DayParams) {
  return useQuery({
    queryKey: attendanceKeys.day(params),
    queryFn: async () =>
      (
        await api.get<AttendanceDay>('/attendance/day', {
          params: {
            ...(params.date ? { date: params.date } : {}),
            ...(params.workplaceId ? { workplace_id: params.workplaceId } : {}),
          },
        })
      ).data,
    placeholderData: (previous) => previous,
    refetchInterval: 60_000,
  })
}

/** KPIs and one row per day for a month or a whole year: mine (`who` = 'me') or an employee's
 *  (attendance.view, in scope). */
export function useAttendanceSummary(who: string, params: SummaryParams, enabled = true) {
  return useQuery({
    queryKey: attendanceKeys.summary(who, params),
    queryFn: async () =>
      (
        await api.get<AttendanceSummary>(
          who === 'me' ? '/attendance/me/summary' : `/attendance/users/${who}/summary`,
          { params: { year: params.year, ...(params.month ? { month: params.month } : {}) } },
        )
      ).data,
    enabled,
    placeholderData: (previous) => previous,
  })
}

/** Every workplace with its current schedule and employee count (archived ones on request). */
export function useWorkplaces(includeArchived = false, enabled = true) {
  return useQuery({
    queryKey: attendanceKeys.workplaces({ includeArchived }),
    queryFn: async () =>
      (
        await api.get<Workplace[]>('/attendance/workplaces', {
          params: includeArchived ? { include_archived: true } : {},
        })
      ).data,
    enabled,
  })
}

/** One workplace, with the employees assigned to it. */
export function useWorkplace(id: string | undefined) {
  return useQuery({
    queryKey: attendanceKeys.workplace(id ?? ''),
    queryFn: async () => (await api.get<Workplace>(`/attendance/workplaces/${id}`)).data,
    enabled: Boolean(id),
  })
}

/** Active workplaces (id, name, default) for the user form and the users list filter
 *  (users.view or a workplace permission). */
export function useWorkplaceOptions(enabled = true) {
  return useQuery({
    queryKey: attendanceKeys.workplaceOptions,
    queryFn: async () => (await api.get<WorkplaceOption[]>('/attendance/workplace-options')).data,
    enabled,
    staleTime: 60_000,
  })
}

// FastAPI reads a list from a repeated parameter (`workplace_ids=a&workplace_ids=b`).
const repeatLists = { indexes: null }

/** Current and upcoming schedule versions of the chosen workplaces (all when empty). */
export function useScheduling(workplaceIds: string[]) {
  return useQuery({
    queryKey: attendanceKeys.scheduling({ workplaceIds }),
    queryFn: async () =>
      (
        await api.get<Scheduling>('/attendance/scheduling', {
          params: { workplace_ids: workplaceIds },
          paramsSerializer: repeatLists,
        })
      ).data,
    placeholderData: (previous) => previous,
  })
}

/** Each day of a month: tracked, off or mixed at the chosen workplaces. */
export function useAttendanceCalendar(year: number, month: number, workplaceIds: string[]) {
  return useQuery({
    queryKey: attendanceKeys.calendar({ year, month, workplaceIds }),
    queryFn: async () =>
      (
        await api.get<AttendanceCalendar>('/attendance/calendar', {
          params: { year, month, workplace_ids: workplaceIds },
          paramsSerializer: repeatLists,
        })
      ).data,
    placeholderData: (previous) => previous,
  })
}

/** Holidays overlapping a year, by start date. */
export function useHolidays(year: number) {
  return useQuery({
    queryKey: attendanceKeys.holidays({ year }),
    queryFn: async () => (await api.get<Holiday[]>('/attendance/holidays', { params: { year } })).data,
    placeholderData: (previous) => previous,
  })
}

/** After any scheduling change (versions, weekdays, holidays): the scheduling page, today's
 *  state, the day views, the summaries and the workplaces' schedule summaries refetch. */
export function invalidateScheduling(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: attendanceKeys.schedulingAll })
  void queryClient.invalidateQueries({ queryKey: attendanceKeys.calendarAll })
  void queryClient.invalidateQueries({ queryKey: attendanceKeys.holidaysAll })
  void queryClient.invalidateQueries({ queryKey: attendanceKeys.workplacesAll })
  void queryClient.invalidateQueries({ queryKey: attendanceKeys.workplaceAll })
  invalidateAttendance(queryClient)
}

/** "Holiday: Pchum Ben" / "Day off" for a day that isn't tracked. */
export function useDayOffText() {
  const { t } = useTranslation()
  const localized = useLocalized()
  return useCallback(
    (off: DayOff) =>
      off.reason === 'holiday' && off.holidays.length
        ? t('attendance.dayOff.holiday', { name: off.holidays.map((h) => localized(h)).join(', ') })
        : t('attendance.dayOff.weekday'),
    [t, localized],
  )
}

/** After a check-in / check-out or a correction: today's state, the day views and the
 *  summaries refetch. */
export function invalidateAttendance(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: attendanceKeys.meToday })
  void queryClient.invalidateQueries({ queryKey: attendanceKeys.dayAll })
  void queryClient.invalidateQueries({ queryKey: attendanceKeys.summaryAll })
  // A fix changes the month's balance, which the Requests tab shows.
  void queryClient.invalidateQueries({ queryKey: ['attendance-requests'] })
}

/** After a workplace change: the lists, the workplace pages and everything above (windows, the
 * user form's options) refetch. `next` is written into its page's cache. */
export function invalidateWorkplaces(queryClient: QueryClient, next?: Workplace) {
  if (next) queryClient.setQueryData(attendanceKeys.workplace(next.id), next)
  void queryClient.invalidateQueries({ queryKey: attendanceKeys.workplacesAll })
  void queryClient.invalidateQueries({ queryKey: attendanceKeys.workplaceAll })
  void queryClient.invalidateQueries({ queryKey: attendanceKeys.workplaceOptions })
  invalidateAttendance(queryClient)
}

/** "07:12" for an API instant, in the business time zone (whatever the device's zone is). */
export function clockTime(iso: string | null | undefined, timeZone = BUSINESS_TZ): string {
  if (!iso) return '—'
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone,
  }).format(new Date(iso))
}

/** Today's date (YYYY-MM-DD) in the business time zone. */
export function businessToday(timeZone = BUSINESS_TZ): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone }).format(new Date())
}

/** Shift name in the UI language ("Morning shift" / "វេនព្រឹក"). */
export function useShiftName() {
  const { t } = useTranslation()
  return useCallback((code: ShiftCode | string | null | undefined) => (code ? t(`attendance.shifts.${code}`) : ''), [t])
}

/** "Late 12 min" / "Present" / "Absent" for a record. */
export function useStatusText() {
  const { t } = useTranslation()
  return useCallback(
    (record: AttendanceRecord) =>
      record.status === 'late'
        ? t('attendance.status.lateMinutes', { count: record.late_minutes })
        : t(`attendance.status.${record.status}`),
    [t],
  )
}

export function statusTone(record: AttendanceRecord | null): 'green' | 'amber' | 'red' | 'neutral' {
  if (!record) return 'neutral'
  return record.status === 'present' ? 'green' : record.status === 'late' ? 'amber' : 'red'
}

/**
 * Minutes as "1 h 05 min" / "7 h" / "20 min" ("ម៉ោង / នាទី" in Khmer), no decimals; `signed`
 * adds "+" / "−" (nothing for 0).
 */
export function useDuration() {
  const { t } = useTranslation()
  return useCallback(
    (minutes: number, signed = false) => {
      const abs = Math.abs(Math.round(minutes))
      const h = Math.floor(abs / 60)
      const m = abs % 60
      const text =
        h && m
          ? t('attendance.duration.hm', { h, m: String(m).padStart(2, '0') })
          : h
            ? t('attendance.duration.h', { h })
            : t('attendance.duration.m', { m })
      if (!signed || abs === 0) return text
      return `${minutes > 0 ? '+' : '−'}${text}`
    },
    [t],
  )
}
