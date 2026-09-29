// Minimal typings for the parts of Telegram.WebApp we use.
// Full reference: https://core.telegram.org/bots/webapps#initializing-mini-apps

interface TelegramBackButton {
  isVisible: boolean
  show(): void
  hide(): void
  onClick(cb: () => void): void
  offClick(cb: () => void): void
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
  /** e.g. 'deactivated' (Bot API 8.0+: the Mini App was minimized or is being closed). */
  onEvent?(event: string, cb: () => void): void
  offEvent?(event: string, cb: () => void): void
}

interface Window {
  Telegram?: { WebApp?: TelegramWebApp }
}
