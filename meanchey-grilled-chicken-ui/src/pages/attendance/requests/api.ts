import { useQuery, type QueryClient } from '@tanstack/react-query'
import { usePermission } from '@/auth/usePermission'
import { api } from '@/lib/api'
import type {
  AttendanceRequest,
  AttendanceRequestPage,
  AttendanceRequestSettings,
  MyRequests,
  RequestEligibility,
  RequestStatus,
} from '@/lib/types'
import { attendanceKeys, businessToday, useHasAttendance } from '../api'

export const REVIEW_PERMISSION = 'attendance.requests_review'

/** Query keys (see docs/ARCHITECTURE.md). */
export const requestKeys = {
  /** Everything under 'attendance-requests': mine and the lists. */
  all: ['attendance-requests'] as const,
  me: (year: number) => ['attendance-requests', 'me', year] as const,
  list: (params: RequestListParams) => ['attendance-requests', params] as const,
  one: (id: string) => ['attendance-request', id] as const,
  oneAll: ['attendance-request'] as const,
  settings: ['attendance-request-settings'] as const,
}

export interface RequestListParams {
  /** '' = every status. */
  status: RequestStatus | 'no_request' | ''
  year: number | null
  month: number | null
  userId: string
  page: number
}

export function useMyRequests(year: number, enabled = true) {
  const tracked = useHasAttendance()
  return useQuery({
    queryKey: requestKeys.me(year),
    queryFn: async () => (await api.get<MyRequests>('/attendance/requests/me', { params: { year } })).data,
    enabled: enabled && tracked,
  })
}

export function useRequestList(params: RequestListParams, enabled = true) {
  const canReview = usePermission(REVIEW_PERMISSION)
  return useQuery({
    queryKey: requestKeys.list(params),
    queryFn: async () =>
      (
        await api.get<AttendanceRequestPage>('/attendance/requests', {
          params: {
            ...(params.status ? { status: params.status } : {}),
            ...(params.year ? { year: params.year } : {}),
            ...(params.month ? { month: params.month } : {}),
            ...(params.userId ? { user_id: params.userId } : {}),
            page: params.page,
          },
        })
      ).data,
    enabled: enabled && canReview,
    placeholderData: (previous) => previous,
  })
}

export function useRequest(id: string | null) {
  return useQuery({
    queryKey: requestKeys.one(id ?? ''),
    queryFn: async () => (await api.get<AttendanceRequest>(`/attendance/requests/${id}`)).data,
    enabled: Boolean(id),
  })
}

/** Pending requests in the reviewer's scope (the sub-tab badge); 0 without the permission. */
export function usePendingRequestCount(): number {
  const canReview = usePermission(REVIEW_PERMISSION)
  const query = useQuery({
    queryKey: requestKeys.list({ status: 'pending', year: null, month: null, userId: '', page: 1 }),
    queryFn: async () =>
      (await api.get<AttendanceRequestPage>('/attendance/requests', { params: { status: 'pending' } })).data,
    enabled: canReview,
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
  return canReview ? (query.data?.pending_count ?? 0) : 0
}

export function useRequestSettings(enabled = true) {
  return useQuery({
    queryKey: requestKeys.settings,
    queryFn: async () => (await api.get<AttendanceRequestSettings>('/attendance/settings/requests')).data,
    enabled,
  })
}

/** After a request was sent or reviewed: the lists, that request and every summary (the strip and
 *  the month lock) are refetched; day views too, since a locked month hides the Fix actions. */
export function invalidateRequests(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: requestKeys.all })
  void queryClient.invalidateQueries({ queryKey: requestKeys.oneAll })
  void queryClient.invalidateQueries({ queryKey: attendanceKeys.summaryAll })
  void queryClient.invalidateQueries({ queryKey: attendanceKeys.dayAll })
}

/** The state that decides what a month shows: a request wins, else the eligibility. */
export type MonthState = 'create' | 'not_needed' | 'not_open' | 'no_request' | RequestStatus

export function monthState(eligibility: RequestEligibility, request: { status: RequestStatus } | null): MonthState {
  if (request) return request.status
  if (eligibility === 'eligible') return 'create'
  if (eligibility === 'window_not_open') return 'not_open'
  if (eligibility === 'window_closed') return 'no_request'
  return 'not_needed'
}

/** "2026-11-01" opens on the 1st of the next month: the current month is `YYYY-MM`. */
export function currentYearMonth(): { year: number; month: number } {
  const [year, month] = businessToday().split('-').map(Number)
  return { year, month }
}
