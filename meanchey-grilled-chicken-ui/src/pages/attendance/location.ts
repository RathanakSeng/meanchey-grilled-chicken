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
  | { status: 'ok'; position: Position }
  /** The user refused access (Telegram or the browser). */
  | { status: 'denied' }
  /** No GPS fix, a timeout, or no location API at all. */
  | { status: 'unavailable' }

/** Telegram's LocationManager (Bot API 8.0+) inside the Mini App, when the client has it. */
function telegramLocation(): TelegramLocationManager | null {
  const manager = isTelegramMiniApp ? telegram?.LocationManager : undefined
  return manager ?? null
}

function browserPosition(): Promise<Position | 'denied' | 'unavailable'> {
  return new Promise((resolve) => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      resolve('unavailable')
      return
    }
    navigator.geolocation.getCurrentPosition(
      (p) =>
        resolve({
          latitude: p.coords.latitude,
          longitude: p.coords.longitude,
          accuracy: p.coords.accuracy,
          at: Date.now(),
        }),
      (err) => resolve(err.code === err.PERMISSION_DENIED ? 'denied' : 'unavailable'),
      { enableHighAccuracy: true, timeout: 20_000, maximumAge: 0 },
    )
  })
}

function telegramPosition(manager: TelegramLocationManager): Promise<Position | 'denied' | 'unavailable' | 'fallback'> {
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

/**
 * The phone's GPS position, read as soon as the screen opens: Telegram's LocationManager in the
 * Mini App (it asks for access once per bot), otherwise `navigator.geolocation` with high
 * accuracy. `refresh()` reads it again; `openSettings` (Telegram only) opens the bot's location
 * settings after a refusal.
 */
export function useDeviceLocation() {
  const [state, setState] = useState<LocationState>({ status: 'locating' })
  const run = useRef(0)

  const refresh = useCallback(async () => {
    const id = ++run.current
    setState((prev) => ({ status: 'locating', position: prev.status === 'ok' ? prev.position : undefined }))
    const manager = telegramLocation()
    let result: Position | 'denied' | 'unavailable' | 'fallback' = 'fallback'
    if (manager) result = await telegramPosition(manager)
    if (result === 'fallback') result = await browserPosition()
    if (id !== run.current) return // a newer read started
    if (result === 'denied' || result === 'unavailable') setState({ status: result })
    else setState({ status: 'ok', position: result })
  }, [])

  useEffect(() => {
    void refresh()
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
