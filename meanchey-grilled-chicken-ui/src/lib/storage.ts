// localStorage can throw (private mode, blocked storage); fall back to memory.
const memory = new Map<string, string>()

export const storage = {
  get(key: string): string | null {
    try {
      return window.localStorage.getItem(key)
    } catch {
      return memory.get(key) ?? null
    }
  },
  set(key: string, value: string): void {
    memory.set(key, value)
    try {
      window.localStorage.setItem(key, value)
    } catch {
      /* ignore */
    }
  },
  remove(key: string): void {
    memory.delete(key)
    try {
      window.localStorage.removeItem(key)
    } catch {
      /* ignore */
    }
  },
}

const ACCESS = 'mc.accessToken'
const REFRESH = 'mc.refreshToken'

export const tokenStore = {
  getAccess: () => storage.get(ACCESS),
  getRefresh: () => storage.get(REFRESH),
  set(pair: { access_token: string; refresh_token: string }) {
    storage.set(ACCESS, pair.access_token)
    storage.set(REFRESH, pair.refresh_token)
  },
  clear() {
    storage.remove(ACCESS)
    storage.remove(REFRESH)
  },
}
