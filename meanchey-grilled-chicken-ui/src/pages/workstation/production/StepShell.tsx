import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Icon } from '@/components/icons'
import { Alert, Button, ConfirmDialog, Input, Spinner, cx } from '@/components/ui'
import { useIsMobileLayout } from '@/layouts/useIsMobileLayout'
import { useErrorMessage } from '@/lib/errors'
import type { FieldError } from './steps'
import type { SaveStatus, useAutosaveDraft } from './useAutosaveDraft'

type Autosave = ReturnType<typeof useAutosaveDraft<unknown>>

/** A labelled number input: decimal keypad for kg / g, numeric for counts; big touch targets. */
export function NumberField({
  label,
  value,
  onChange,
  unit,
  mode,
  error,
  hint,
  compact = false,
}: {
  label: ReactNode
  value: string
  onChange(value: string): void
  unit?: string
  mode: 'decimal' | 'numeric'
  error?: FieldError | null
  hint?: ReactNode
  compact?: boolean
}) {
  const { t } = useTranslation()
  return (
    <label className="block">
      <span className={cx('mb-1 block font-medium text-stone-700', compact ? 'text-xs' : 'text-sm')}>
        {label}
      </span>
      <span className="relative block">
        <Input
          inputMode={mode}
          autoComplete="off"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={error ? true : undefined}
          className={cx(
            'h-12 text-base tabular-nums sm:h-10 sm:text-sm',
            unit && 'pr-12',
            error && 'ring-red-400 focus:ring-red-500',
          )}
        />
        {unit && (
          <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-stone-400">
            {unit}
          </span>
        )}
      </span>
      {error ? (
        <span className="mt-1 block text-xs text-red-600">{t(`production.errors.${error}`)}</span>
      ) : (
        hint && <span className="mt-1 block text-xs text-stone-500">{hint}</span>
      )}
    </label>
  )
}

/** A computed value shown like a field, with a lock (e.g. wing count = 2 × chickens). */
export function LockedValue({ label, value, hint }: { label: ReactNode; value: ReactNode; hint: ReactNode }) {
  return (
    <div>
      <span className="mb-1 block text-sm font-medium text-stone-700">{label}</span>
      <span className="flex h-12 items-center gap-2 rounded-lg bg-stone-100 px-3 text-base tabular-nums text-stone-700 ring-1 ring-inset ring-stone-200 sm:h-10 sm:text-sm">
        <Icon name="lock" width={16} height={16} className="text-stone-400" />
        {value}
      </span>
      <span className="mt-1 block text-xs text-stone-500">{hint}</span>
    </div>
  )
}

function useNow(intervalMs: number) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs])
  return now
}

export function AutosaveStatus({ status, savedAt }: { status: SaveStatus; savedAt: Date | null }) {
  const { t, i18n } = useTranslation()
  const now = useNow(30_000)
  const time = savedAt
    ? new Intl.DateTimeFormat(i18n.language === 'km' ? 'km-KH' : 'en-GB', {
        timeStyle: 'short',
      }).format(savedAt)
    : ''
  const content: Record<SaveStatus, [ReactNode, string, string]> = {
    idle: [<Icon key="i" name="check" width={14} height={14} />, t('production.autosave.idle'), 'text-stone-400'],
    saving: [<Spinner key="i" className="h-3.5 w-3.5" />, t('production.autosave.saving'), 'text-stone-500'],
    saved: [
      <Icon key="i" name="check" width={14} height={14} />,
      savedAt && now - savedAt.getTime() < 60_000
        ? t('production.autosave.savedJustNow')
        : t('production.autosave.savedAt', { time }),
      'text-green-700',
    ],
    offline: [<Icon key="i" name="alert" width={14} height={14} />, t('production.autosave.offline'), 'text-amber-700'],
    retrying: [<Spinner key="i" className="h-3.5 w-3.5" />, t('production.autosave.retrying'), 'text-amber-700'],
    failed: [<Icon key="i" name="alert" width={14} height={14} />, t('production.autosave.failed'), 'text-red-600'],
    conflict: [<Icon key="i" name="alert" width={14} height={14} />, t('production.autosave.conflict'), 'text-red-600'],
  }
  const [icon, label, tone] = content[status]
  return (
    <span role="status" aria-live="polite" className={cx('inline-flex items-center gap-1.5 text-xs font-medium', tone)}>
      {icon}
      {label}
    </span>
  )
}

/**
 * Card around a step form: header with the autosave status, restore / conflict notices, the
 * form, and the Finish button (sticky above the bottom bar on mobile). Finish flushes the draft,
 * asks for confirmation, then calls `onFinish`.
 */
export function StepShell({
  title,
  autosave,
  fieldLabel,
  blockers,
  onFinish,
  finishing,
  finishError,
  children,
}: {
  title: ReactNode
  autosave: Autosave
  /** Label of a payload key (for the conflict notice). */
  fieldLabel(key: string): string
  /** Reasons Finish is disabled (translated); empty = ready. */
  blockers: string[]
  onFinish(): void
  finishing: boolean
  finishError: unknown
  children: ReactNode
}) {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const isMobile = useIsMobileLayout()
  const [confirming, setConfirming] = useState(false)
  const ready = blockers.length === 0 && autosave.status !== 'conflict'

  const finishButton = (
    <Button
      block={isMobile}
      className={cx(isMobile && 'h-12 text-base')}
      disabled={!ready}
      loading={finishing}
      onClick={() => setConfirming(true)}
    >
      <Icon name="check" width={18} height={18} />
      {t('production.finishStep')}
    </Button>
  )

  return (
    <section className="rounded-xl bg-white shadow-sm ring-1 ring-stone-200">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-stone-100 px-4 py-3 sm:px-5">
        <h2 className="text-base font-semibold text-stone-900">{title}</h2>
        <AutosaveStatus status={autosave.status} savedAt={autosave.savedAt} />
      </header>

      <div className="space-y-4 p-4 sm:p-5">
        {autosave.restore && (
          <Alert tone="warning">
            <p className="font-medium">{t('production.restore.title')}</p>
            <p className="mt-0.5">{t('production.restore.body')}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button onClick={autosave.applyRestore}>{t('production.restore.restore')}</Button>
              <Button variant="secondary" onClick={autosave.discardRestore}>
                {t('production.restore.discard')}
              </Button>
            </div>
          </Alert>
        )}
        {autosave.conflict && (
          <Alert tone="error">
            <p className="font-medium">{t('production.conflict.title')}</p>
            <p className="mt-0.5">
              {autosave.conflictFields.length > 0
                ? t('production.conflict.changed', {
                    fields: autosave.conflictFields.map(fieldLabel).join(', '),
                  })
                : t('production.conflict.body')}
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button onClick={() => autosave.resolveConflict(true)}>
                {t('production.conflict.keepMine')}
              </Button>
              <Button variant="secondary" onClick={() => autosave.resolveConflict(false)}>
                {t('production.conflict.useTheirs')}
              </Button>
            </div>
          </Alert>
        )}
        {autosave.status === 'failed' && autosave.errorCode && (
          <Alert tone="error">{t(`errors.${autosave.errorCode}`, { defaultValue: t('errors.UNKNOWN') })}</Alert>
        )}

        {children}

        {finishError !== null && finishError !== undefined && (
          <Alert tone="error">{errorMessage(finishError)}</Alert>
        )}
        {blockers.length > 0 && (
          <ul className="space-y-0.5 text-xs text-stone-500">
            {blockers.map((b) => (
              <li key={b} className="flex items-start gap-1">
                <span aria-hidden>•</span>
                {b}
              </li>
            ))}
          </ul>
        )}
        {!isMobile && <div className="flex justify-end">{finishButton}</div>}
      </div>

      {isMobile && (
        <>
          {/* Space so the sticky bar never covers the last field. */}
          <div className="h-20" aria-hidden />
          <div
            className="fixed inset-x-0 z-20 border-t border-stone-200 bg-white/95 px-4 py-2 backdrop-blur"
            style={{ bottom: 'calc(3.6rem + env(safe-area-inset-bottom))' }}
          >
            {finishButton}
          </div>
        </>
      )}

      <ConfirmDialog
        open={confirming}
        title={t('production.finishConfirmTitle')}
        body={t('production.finishConfirmBody')}
        confirmLabel={t('production.finishStep')}
        loading={finishing}
        onConfirm={() => {
          setConfirming(false)
          onFinish()
        }}
        onClose={() => setConfirming(false)}
      />
    </section>
  )
}
