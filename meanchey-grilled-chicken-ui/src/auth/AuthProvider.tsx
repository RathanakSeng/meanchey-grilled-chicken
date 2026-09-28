import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { setLanguage } from '@/i18n'
import { api, AUTH_LOGOUT_EVENT, AUTH_REFRESH_ME_EVENT } from '@/lib/api'
import { getError } from '@/lib/errors'
import { tokenStore } from '@/lib/storage'
import { isTelegramMiniApp, telegram } from '@/lib/telegram'
import type { Me, TokenPair } from '@/lib/types'

export type AuthStatus = 'booting' | 'anonymous' | 'authenticated' | 'offline'

interface AuthContextValue {
  status: AuthStatus
  me: Me | null
  /** Error code from the automatic Telegram Mini App login, if it failed. */
  telegramError: string | null
  login(username: string, password: string): Promise<void>
  loginWithTelegram(): Promise<void>
  logout(options?: { skipServer?: boolean }): Promise<void>
  refreshMe(): Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export const ME_QUERY_KEY = ['me'] as const
const ME_STALE_TIME = 60_000

async function fetchMe(): Promise<Me> {
  return (await api.get<Me>('/auth/me')).data
}

/**
 * Refetch /auth/me when this component mounts and the cached copy is older than a minute, so
 * menus built from permissions (Home tiles, Settings hub) pick up grants/revokes. Only use
 * inside signed-in routes.
 */
export function useRefreshMeWhenStale(): void {
  useQuery({ queryKey: ME_QUERY_KEY, queryFn: fetchMe, retry: false, staleTime: ME_STALE_TIME })
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [hasToken, setHasToken] = useState(() => tokenStore.getAccess() !== null)
  const [telegramPending, setTelegramPending] = useState(() => !hasToken && isTelegramMiniApp)
  const [telegramError, setTelegramError] = useState<string | null>(null)

  const meQuery = useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: fetchMe,
    enabled: hasToken,
    retry: false,
    staleTime: ME_STALE_TIME,
  })

  const applyTokens = useCallback(
    async (pair: TokenPair) => {
      tokenStore.set(pair)
      queryClient.removeQueries()
      setHasToken(true)
    },
    [queryClient],
  )

  const loginWithTelegram = useCallback(async () => {
    setTelegramError(null)
    setTelegramPending(true)
    try {
      const { data } = await api.post<TokenPair>('/auth/telegram', {
        init_data: telegram?.initData ?? '',
      })
      await applyTokens(data)
    } catch (err) {
      setTelegramError(getError(err).code)
    } finally {
      setTelegramPending(false)
    }
  }, [applyTokens])

  // Inside the Telegram Mini App, sign in automatically.
  const autoLoginStarted = useRef(false)
  useEffect(() => {
    if (!autoLoginStarted.current && telegramPending) {
      autoLoginStarted.current = true
      void loginWithTelegram()
    }
  }, [telegramPending, loginWithTelegram])

  const login = useCallback(
    async (username: string, password: string) => {
      const { data } = await api.post<TokenPair>('/auth/login', { username, password })
      await applyTokens(data)
    },
    [applyTokens],
  )

  const clearSession = useCallback(() => {
    tokenStore.clear()
    queryClient.clear()
    setHasToken(false)
  }, [queryClient])

  const logout = useCallback(
    async ({ skipServer = false }: { skipServer?: boolean } = {}) => {
      if (!skipServer) {
        try {
          await api.post('/auth/logout', { refresh_token: tokenStore.getRefresh() })
        } catch {
          /* the session is cleared locally regardless */
        }
      }
      clearSession()
    },
    [clearSession],
  )

  const refreshMe = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY })
  }, [queryClient])

  // Events raised by the axios interceptor.
  useEffect(() => {
    const onLogout = () => clearSession()
    const onRefreshMe = () => void refreshMe()
    window.addEventListener(AUTH_LOGOUT_EVENT, onLogout)
    window.addEventListener(AUTH_REFRESH_ME_EVENT, onRefreshMe)
    return () => {
      window.removeEventListener(AUTH_LOGOUT_EVENT, onLogout)
      window.removeEventListener(AUTH_REFRESH_ME_EVENT, onRefreshMe)
    }
  }, [clearSession, refreshMe])

  // A rejected /auth/me (after the interceptor's refresh attempt) ends the session;
  // a network failure does not, so the user can retry.
  const meErrorCode = meQuery.isError ? getError(meQuery.error).code : null
  const offline = meErrorCode === 'NETWORK_ERROR'
  useEffect(() => {
    if (meErrorCode && meErrorCode !== 'NETWORK_ERROR') clearSession()
  }, [meErrorCode, clearSession])

  // Apply the user's saved language once per sign-in (and when it changes on the server).
  const appliedLanguage = useRef<string | null>(null)
  const me = meQuery.data ?? null
  useEffect(() => {
    if (!me) {
      appliedLanguage.current = null
      return
    }
    const key = `${me.user.id}:${me.user.language}`
    if (appliedLanguage.current !== key) {
      appliedLanguage.current = key
      setLanguage(me.user.language)
    }
  }, [me])

  const status: AuthStatus =
    telegramPending || (hasToken && meQuery.isPending)
      ? 'booting'
      : me && hasToken
        ? 'authenticated'
        : hasToken && offline
          ? 'offline'
          : 'anonymous'

  const value = useMemo<AuthContextValue>(
    () => ({ status, me, telegramError, login, loginWithTelegram, logout, refreshMe }),
    [status, me, telegramError, login, loginWithTelegram, logout, refreshMe],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
