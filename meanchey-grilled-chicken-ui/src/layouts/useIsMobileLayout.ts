import { useEffect, useState } from 'react'
import { isTelegramMiniApp } from '@/lib/telegram'

const QUERY = '(max-width: 767px)'

/** Mobile layout inside the Telegram Mini App, or on narrow screens. */
export function useIsMobileLayout(): boolean {
  const [narrow, setNarrow] = useState(() => window.matchMedia(QUERY).matches)
  useEffect(() => {
    const mql = window.matchMedia(QUERY)
    const onChange = () => setNarrow(mql.matches)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])
  return isTelegramMiniApp || narrow
}
