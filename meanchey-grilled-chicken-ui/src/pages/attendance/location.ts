import { useCallback, useEffect, useRef, useState } from 'react'
import { isTelegramMiniApp, telegram } from '@/lib/telegram'

export interface Position {
  latitude: number
  longitude: number
  /** Metres (GPS horizontal accuracy). */
  accuracy: number
  /** Device time it was read (ms), only to show "just now". */
  at: number
}

export type LocationState =
  | { status: 'locating'; position?: Position }
  /** `improving`: still listening for a more accurate reading (`position` is the best so far). */
  | { status: 'ok'; position: Position; improving: boolean }
  /** The user refused access (Telegram or the browser). */
  | { status: 'denied' }
  /** No GPS fix, a timeout, or no location API at all. */
  | { status: 'unavailable' }

/** How long one read keeps listening for a better reading, and the accuracy that ends it early. */
const LISTEN_MS = 20_000
const GOOD_ENOUGH_M = 20
/** Telegram's LocationManager has no watch: it's asked again this often. */
const TELEGRAM_POLL_MS = 1_500

/** Telegram's LocationManager (Bot API 8.0+) inside the Mini App, when the client has it. */
function telegramLocation(): TelegramLocationManager | null {
  const manager = isTelegramMiniApp ? telegram?.LocationManager : undefined
  return manager ?? null
}

type Outcome = 'done' | 'denied' | 'unavailable'

/** `navigator.geolocation.watchPosition` until `signal` aborts; a failure only counts before the first fix. */
function listenBrowser(onFix: (p: Position) => void, signal: AbortSignal): Promise<Outcome> {
  return new Promise((resolve) => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      resolve('unavailable')
      return
    }
    let got = false
    const end = (outcome: Outcome) => {
      navigator.geolocation.clearWatch(watch)
      signal.removeEventListener('abort', onAbort)
      resolve(outcome)
    }
    const onAbort = () => end(got ? 'done' : 'unavailable')
    const watch = navigator.geolocation.watchPosition(
      (p) => {
        got = true
        onFix({ latitude: p.coords.latitude, longitude: p.coords.longitude, accuracy: p.coords.accuracy, at: Date.now() })
      },
      (err) => {
        if (!got) end(err.code === err.PERMISSION_DENIED ? 'denied' : 'unavailable')
      },
      { enableHighAccuracy: true, timeout: LISTEN_MS, maximumAge: 0 },
    )
    if (signal.aborted) onAbort()
    else signal.addEventListener('abort', onAbort)
  })
}

function telegramPosition(manager: TelegramLocationManager): Promise<Position | Outcome | 'fallback'> {
  return new Promise((resolve) => {
    const read = () => {
      if (!manager.isLocationAvailable) {
        resolve('fallback')
        return
      }
      manager.getLocation((data) => {
        if (!data) {
          resolve(manager.isAccessRequested && !manager.isAccessGranted ? 'denied' : 'unavailable')
          return
        }
        if (data.horizontal_accuracy === null) {
          // Without an accuracy we can't tell how good the fix is: ask the browser instead.
          resolve('fallback')
          return
        }
        resolve({
          latitude: data.latitude,
          longitude: data.longitude,
          accuracy: data.horizontal_accuracy,
          at: Date.now(),
        })
      })
    }
    if (manager.isInited) read()
    else manager.init(read)
  })
}

/** Telegram readings, one every TELEGRAM_POLL_MS, until `signal` aborts; a failure only counts before the first fix. */
async function listenTelegram(
  manager: TelegramLocationManager,
  onFix: (p: Position) => void,
  signal: AbortSignal,
): Promise<Outcome | 'fallback'> {
  let got = false
  while (!signal.aborted) {
    const p = await telegramPosition(manager)
    if (typeof p === 'string') return got ? 'done' : p
    got = true
    onFix(p)
    await new Promise((r) => setTimeout(r, TELEGRAM_POLL_MS))
  }
  return got ? 'done' : 'unavailable'
}

/**
 * The phone's GPS position, read as soon as the screen opens: Telegram's LocationManager in the
 * Mini App (it asks for access once per bot), otherwise `navigator.geolocation` with high
 * accuracy. A first reading is often rough (indoors, just after opening), so each read keeps
 * listening for up to LISTEN_MS and keeps the most accurate reading (`improving` meanwhile),
 * stopping early once it's within GOOD_ENOUGH_M. `refresh()` starts a new read; `openSettings`
 * (Telegram only) opens the bot's location settings after a refusal.
 */
export function useDeviceLocation() {
  const [state, setState] = useState<LocationState>({ status: 'locating' })
  const current = useRef<AbortController | null>(null)

  const refresh = useCallback(async () => {
    current.current?.abort()
    const read = new AbortController()
    current.current = read
    setState((prev) => ({ status: 'locating', position: prev.status === 'ok' ? prev.position : undefined }))
    let best: Position | undefined
    const onFix = (p: Position) => {
      if (read.signal.aborted || (best && p.accuracy > best.accuracy)) return
      best = p
      setState({ status: 'ok', position: p, improving: true })
      if (p.accuracy <= GOOD_ENOUGH_M) read.abort()
    }
    const timer = setTimeout(() => read.abort(), LISTEN_MS)
    read.signal.addEventListener('abort', () => {
      clearTimeout(timer)
      if (current.current === read && best) setState({ status: 'ok', position: best, improving: false })
    })
    const manager = telegramLocation()
    let outcome: Outcome | 'fallback' = manager ? await listenTelegram(manager, onFix, read.signal) : 'fallback'
    if (outcome === 'fallback' && !read.signal.aborted) outcome = await listenBrowser(onFix, read.signal)
    if (current.current !== read) return // a newer read started, or the screen closed
    if (best) read.abort() // stopped listening: no longer improving
    else if (outcome === 'denied' || outcome === 'unavailable') setState({ status: outcome })
  }, [])

  useEffect(() => {
    void refresh()
    return () => {
      const read = current.current
      current.current = null
      read?.abort()
    }
  }, [refresh])

  const manager = telegramLocation()
  const openSettings = manager ? () => manager.openSettings() : undefined
  return { state, refresh, openSettings }
}

/** Great-circle distance in metres (the API's haversine, for the live status line only). */
export function distanceM(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const rad = Math.PI / 180
  const dp = (lat2 - lat1) * rad
  const dl = (lng2 - lng1) * rad
  const a = Math.sin(dp / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dl / 2) ** 2
  return 2 * 6_371_008.8 * Math.asin(Math.min(1, Math.sqrt(a)))
}
