import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { tokenStore } from './storage'
import type { ApiErrorBody, TokenPair } from './types'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export const AUTH_LOGOUT_EVENT = 'auth:logout'
/** /auth/me is out of date (password change pending, or permissions/role changed). */
export const AUTH_REFRESH_ME_EVENT = 'auth:refresh-me'

// A 403 with one of these codes means our cached permissions/role may be stale.
const REFRESH_ME_CODES = new Set([
  'PASSWORD_CHANGE_REQUIRED',
  'MISSING_PERMISSION',
  'FORBIDDEN_ROLE',
  'FORBIDDEN_SCOPE',
])

export const api = axios.create({ baseURL: API_BASE_URL })

api.interceptors.request.use((config) => {
  const token = tokenStore.getAccess()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

const NO_REFRESH_PATHS = ['/auth/login', '/auth/telegram', '/auth/refresh']
const REFRESHABLE_CODES = new Set(['TOKEN_EXPIRED', 'INVALID_TOKEN'])

// Single-flight: concurrent 401s share one refresh request.
let refreshing: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  const refreshToken = tokenStore.getRefresh()
  if (!refreshToken) throw new Error('No refresh token')
  const { data } = await axios.post<TokenPair>(`${API_BASE_URL}/auth/refresh`, {
    refresh_token: refreshToken,
  })
  tokenStore.set(data)
  return data.access_token
}

function forceLogout() {
  tokenStore.clear()
  window.dispatchEvent(new Event(AUTH_LOGOUT_EVENT))
}

type RetriableConfig = InternalAxiosRequestConfig & { _retry?: boolean }

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiErrorBody>) => {
    const original = error.config as RetriableConfig | undefined
    const status = error.response?.status
    const code = error.response?.data?.error?.code

    const refreshable =
      original &&
      status === 401 &&
      !original._retry &&
      code !== undefined &&
      REFRESHABLE_CODES.has(code) &&
      !NO_REFRESH_PATHS.some((p) => original.url?.endsWith(p)) &&
      tokenStore.getRefresh() !== null

    if (refreshable) {
      original._retry = true
      try {
        refreshing ??= refreshAccessToken().finally(() => {
          refreshing = null
        })
        const token = await refreshing
        original.headers.Authorization = `Bearer ${token}`
        return api(original)
      } catch {
        forceLogout()
        return Promise.reject(error)
      }
    }

    if (status === 401 && code === 'ACCOUNT_DISABLED') forceLogout()
    if (status === 403 && code !== undefined && REFRESH_ME_CODES.has(code)) {
      window.dispatchEvent(new Event(AUTH_REFRESH_ME_EVENT))
    }
    return Promise.reject(error)
  },
)
