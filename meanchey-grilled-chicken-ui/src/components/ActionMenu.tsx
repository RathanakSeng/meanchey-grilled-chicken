import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Icon, type IconName } from './icons'
import { cx } from './ui'

export interface ActionMenuItem {
  key: string
  label: string
  icon?: IconName
  tone?: 'default' | 'danger'
  onSelect(): void
}

const MENU_WIDTH = 192

/**
 * A "⋮" button with a small menu. The menu uses fixed positioning, so it isn't clipped by
 * scrolling/overflow containers such as tables. Renders nothing when there are no items.
 */
export function ActionMenu({ items, label }: { items: ActionMenuItem[]; label: string }) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ top: number; left: number; up: boolean } | null>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    if (!open || !buttonRef.current) return
    const r = buttonRef.current.getBoundingClientRect()
    const up = window.innerHeight - r.bottom < 48 * items.length + 16
    setPos({
      top: up ? r.top - 4 : r.bottom + 4,
      left: Math.max(8, Math.min(r.right - MENU_WIDTH, window.innerWidth - MENU_WIDTH - 8)),
      up,
    })
  }, [open, items.length])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent | TouchEvent) => {
      const target = e.target as Node
      if (!menuRef.current?.contains(target) && !buttonRef.current?.contains(target)) {
        setOpen(false)
      }
    }
    const close = () => setOpen(false)
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close()
    document.addEventListener('mousedown', onDown)
    document.addEventListener('touchstart', onDown)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('touchstart', onDown)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (items.length === 0) return null
  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          setOpen((o) => !o)
        }}
        className="rounded-lg p-2 text-stone-500 hover:bg-stone-100 hover:text-stone-800"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
      >
        <Icon name="more" strokeWidth={3} />
      </button>
      {open && pos && (
        <div
          ref={menuRef}
          role="menu"
          style={{
            position: 'fixed',
            left: pos.left,
            width: MENU_WIDTH,
            ...(pos.up ? { bottom: window.innerHeight - pos.top } : { top: pos.top }),
          }}
          className="z-50 overflow-hidden rounded-xl bg-white py-1 shadow-lg ring-1 ring-stone-200"
        >
          {items.map((item) => (
            <MenuButton
              key={item.key}
              tone={item.tone}
              icon={item.icon}
              onClick={() => {
                setOpen(false)
                item.onSelect()
              }}
            >
              {item.label}
            </MenuButton>
          ))}
        </div>
      )}
    </>
  )
}

function MenuButton({
  tone = 'default',
  icon,
  onClick,
  children,
}: {
  tone?: 'default' | 'danger'
  icon?: IconName
  onClick(): void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={cx(
        'flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm',
        tone === 'danger' ? 'text-red-600 hover:bg-red-50' : 'text-stone-700 hover:bg-stone-50',
      )}
    >
      {icon && <Icon name={icon} width={16} height={16} />}
      {children}
    </button>
  )
}
