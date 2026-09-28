import { useEffect, useId, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useIsMobileLayout } from '@/layouts/useIsMobileLayout'
import { Icon } from './icons'
import { cx, useEscapeKey } from './ui'

interface SheetProps {
  open: boolean
  title: ReactNode
  onClose(): void
  children: ReactNode
  /** Sticky footer (e.g. Cancel / Save). */
  footer?: ReactNode
  /** Disable closing by backdrop click / Escape (e.g. while saving). */
  busy?: boolean
}

/**
 * A panel over the page: a side drawer on desktop, a bottom sheet on mobile and in the Mini App.
 * Same conventions as `ConfirmDialog` (aria-modal, Escape to close), for forms and longer content.
 */
export function Sheet({ open, title, onClose, children, footer, busy = false }: SheetProps) {
  const { t } = useTranslation()
  const isMobile = useIsMobileLayout()
  const titleId = useId()
  const close = () => {
    if (!busy) onClose()
  }
  useEscapeKey(open, close)

  // Keep the page behind from scrolling while the sheet is open.
  useEffect(() => {
    if (!open) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [open])

  if (!open) return null
  return (
    <div
      className={cx(
        'fixed inset-0 z-50 flex bg-stone-900/40',
        isMobile ? 'items-end' : 'justify-end',
      )}
      onMouseDown={(e) => e.target === e.currentTarget && close()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={cx(
          'flex w-full flex-col bg-white shadow-xl',
          isMobile ? 'max-h-[90vh] rounded-t-2xl' : 'h-full max-w-md',
        )}
        style={isMobile ? { paddingBottom: 'env(safe-area-inset-bottom)' } : undefined}
      >
        {isMobile && <span className="mx-auto mt-2 h-1 w-10 rounded-full bg-stone-300" aria-hidden />}
        <header className="flex items-center justify-between gap-3 border-b border-stone-100 px-5 py-4">
          <h2 id={titleId} className="text-lg font-semibold text-stone-900">
            {title}
          </h2>
          <button
            type="button"
            onClick={close}
            disabled={busy}
            className="-mr-2 rounded-lg p-1.5 text-stone-500 hover:bg-stone-100 disabled:opacity-50"
            aria-label={t('common.close')}
          >
            <Icon name="close" />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <footer className="border-t border-stone-100 px-5 py-3">{footer}</footer>}
      </div>
    </div>
  )
}
