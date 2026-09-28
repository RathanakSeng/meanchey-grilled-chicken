import {
  forwardRef,
  useEffect,
  useId,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { Icon } from './icons'

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ')
}

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost'

const buttonVariants: Record<ButtonVariant, string> = {
  primary: 'bg-brand-600 text-white hover:bg-brand-700 focus-visible:ring-brand-500',
  secondary:
    'bg-white text-stone-800 ring-1 ring-inset ring-stone-300 hover:bg-stone-50 focus-visible:ring-brand-500',
  danger: 'bg-red-600 text-white hover:bg-red-700 focus-visible:ring-red-500',
  ghost: 'text-stone-700 hover:bg-stone-100 focus-visible:ring-brand-500',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  loading?: boolean
  block?: boolean
}

export function Button({
  variant = 'primary',
  loading = false,
  block = false,
  className,
  children,
  disabled,
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={cx(
        'inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium',
        'transition focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2',
        'disabled:cursor-not-allowed disabled:opacity-60',
        buttonVariants[variant],
        block && 'w-full',
        className,
      )}
      {...props}
    >
      {loading && <Spinner className="h-4 w-4" />}
      {children}
    </button>
  )
}

const controlClass =
  'block w-full rounded-lg border-0 bg-white px-3 py-2 text-sm text-stone-900 shadow-sm ring-1 ring-inset ring-stone-300 placeholder:text-stone-400 focus:ring-2 focus:ring-inset focus:ring-brand-500 disabled:bg-stone-100 disabled:text-stone-500'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return <input ref={ref} className={cx(controlClass, className)} {...props} />
  },
)

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...props }, ref) {
    return (
      <select ref={ref} className={cx(controlClass, 'pr-8', className)} {...props}>
        {children}
      </select>
    )
  },
)

interface FieldProps {
  label: string
  hint?: ReactNode
  children: (id: string) => ReactNode
  className?: string
}

/** Label + control + hint. `children` receives the id to put on the control. */
export function Field({ label, hint, children, className }: FieldProps) {
  const id = useId()
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-stone-700">
        {label}
      </label>
      {children(id)}
      {hint && <p className="mt-1 text-xs text-stone-500">{hint}</p>}
    </div>
  )
}

export function Card({
  title,
  actions,
  children,
  className,
}: {
  title?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cx('rounded-xl bg-white shadow-sm ring-1 ring-stone-200', className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-stone-100 px-4 py-3 sm:px-5">
          {title && <h2 className="text-base font-semibold text-stone-900">{title}</h2>}
          {actions}
        </header>
      )}
      <div className="p-4 sm:p-5">{children}</div>
    </section>
  )
}

type Tone = 'neutral' | 'brand' | 'green' | 'red' | 'amber' | 'blue'

const badgeTones: Record<Tone, string> = {
  neutral: 'bg-stone-100 text-stone-700 ring-stone-200',
  brand: 'bg-brand-50 text-brand-700 ring-brand-200',
  green: 'bg-green-50 text-green-700 ring-green-200',
  red: 'bg-red-50 text-red-700 ring-red-200',
  amber: 'bg-amber-50 text-amber-800 ring-amber-200',
  blue: 'bg-sky-50 text-sky-700 ring-sky-200',
}

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
        badgeTones[tone],
      )}
    >
      {children}
    </span>
  )
}

const alertTones = {
  info: 'bg-sky-50 text-sky-800 ring-sky-200',
  success: 'bg-green-50 text-green-800 ring-green-200',
  warning: 'bg-amber-50 text-amber-900 ring-amber-200',
  error: 'bg-red-50 text-red-800 ring-red-200',
}

export function Alert({
  tone = 'info',
  children,
  className,
}: {
  tone?: keyof typeof alertTones
  children: ReactNode
  className?: string
}) {
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={cx('rounded-lg px-3 py-2 text-sm ring-1 ring-inset', alertTones[tone], className)}
    >
      {children}
    </div>
  )
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cx('animate-spin', className ?? 'h-6 w-6')} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="4" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
    </svg>
  )
}

export function FullScreenSpinner({ label }: { label?: string }) {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-3 p-8 text-brand-600">
      <Spinner className="h-8 w-8" />
      <p className="text-sm text-stone-500">{label ?? t('common.loading')}</p>
    </div>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="py-10 text-center text-sm text-stone-500">{children}</p>
}

export function PageHeader({
  title,
  subtitle,
  actions,
  back,
}: {
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  back?: string
}) {
  const navigate = useNavigate()
  const { t } = useTranslation()
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3 sm:mb-6">
      <div className="flex min-w-0 items-start gap-2">
        {back && (
          <button
            type="button"
            onClick={() => navigate(back)}
            className="-ml-2 mt-0.5 rounded-lg p-1.5 text-stone-500 hover:bg-stone-100"
            aria-label={t('common.back')}
          >
            <Icon name="chevronLeft" />
          </button>
        )}
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold text-stone-900 sm:text-2xl">{title}</h1>
          {subtitle && <div className="mt-1 text-sm text-stone-500">{subtitle}</div>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

interface ConfirmDialogProps {
  open: boolean
  title: string
  body: ReactNode
  confirmLabel: string
  tone?: 'primary' | 'danger'
  loading?: boolean
  error?: string | null
  onConfirm(): void
  onClose(): void
}

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  tone = 'primary',
  loading,
  error,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  const { t } = useTranslation()
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/40 p-4 sm:items-center">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl"
      >
        <h2 id="confirm-title" className="text-lg font-semibold text-stone-900">
          {title}
        </h2>
        <div className="mt-2 text-sm text-stone-600">{body}</div>
        {error && (
          <Alert tone="error" className="mt-3">
            {error}
          </Alert>
        )}
        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose} disabled={loading}>
            {t('common.cancel')}
          </Button>
          <Button variant={tone} onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
