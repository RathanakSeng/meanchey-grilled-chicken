// Minimal typings for the parts of Telegram.WebApp we use.
// Full reference: https://core.telegram.org/bots/webapps#initializing-mini-apps

interface TelegramBackButton {
  isVisible: boolean
  show(): void
  hide(): void
  onClick(cb: () => void): void
  offClick(cb: () => void): void
}

/** Bot API 8.0+: the device location, with the user's permission (granted per bot). */
interface TelegramLocationData {
  latitude: number
  longitude: number
  altitude: number | null
  course: number | null
  speed: number | null
  horizontal_accuracy: number | null
  vertical_accuracy: number | null
  course_accuracy: number | null
  speed_accuracy: number | null
}

interface TelegramLocationManager {
  isInited: boolean
  isLocationAvailable: boolean
  isAccessRequested: boolean
  isAccessGranted: boolean
  init(cb?: () => void): TelegramLocationManager
  /** `null` when access was denied or the location is unavailable. */
  getLocation(cb: (data: TelegramLocationData | null) => void): TelegramLocationManager
  openSettings(): TelegramLocationManager
}

interface TelegramWebApp {
  initData: string
  initDataUnsafe: {
    user?: { id: number; username?: string; first_name?: string; language_code?: string }
  }
  platform: string
  colorScheme: 'light' | 'dark'
  ready(): void
  expand(): void
  close(): void
  setHeaderColor(color: string): void
  setBackgroundColor(color: string): void
  BackButton: TelegramBackButton
  /** Bot API version of the client, e.g. "8.0". */
  version?: string
  LocationManager?: TelegramLocationManager
  /** Opens a t.me link inside Telegram (the Mini App stays open). */
  openTelegramLink?(url: string): void
  /** e.g. 'deactivated' (Bot API 8.0+: the Mini App was minimized or is being closed). */
  onEvent?(event: string, cb: () => void): void
  offEvent?(event: string, cb: () => void): void
}

interface Window {
  Telegram?: { WebApp?: TelegramWebApp }
}
