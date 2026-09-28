export const telegram: TelegramWebApp | undefined =
  typeof window !== 'undefined' ? window.Telegram?.WebApp : undefined

/** True only when actually opened inside Telegram (the script also loads in normal browsers). */
export const isTelegramMiniApp = Boolean(telegram?.initData)

export function initTelegram(): void {
  if (!telegram || !isTelegramMiniApp) return
  telegram.ready()
  telegram.expand()
  try {
    telegram.setHeaderColor('#ea580c')
    telegram.setBackgroundColor('#fafaf9')
  } catch {
    /* older clients */
  }
}
