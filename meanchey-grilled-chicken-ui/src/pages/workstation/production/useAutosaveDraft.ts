import { useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { getError } from '@/lib/errors'
import { storage } from '@/lib/storage'
import { telegram } from '@/lib/telegram'
import type { ProductionBatch, StepNumber } from '@/lib/types'
import { keepaliveSave, productionKeys, slugOf, stepData } from './api'

export const AUTOSAVE_DELAY_MS = 1500
const RETRY_DELAY_MS = 5000

export type SaveStatus =
  | 'idle' // nothing typed yet
  | 'saving' // changes waiting for the debounce, or a request in flight
  | 'saved'
  | 'offline' // no connection: kept on this device, sent when back online
  | 'retrying' // the server failed; retried automatically
  | 'failed' // can't be saved any more (e.g. someone finished the step): the batch is reloaded
  | 'conflict' // someone else saved first: the user decides

/** What's kept in localStorage under `mc.draft.<batchId>.<step>`. */
export interface LocalDraft<V> {
  values: V
  /** Server version the values were based on. */
  baseVersion: number
  savedAt: number
}

interface Options<V> {
  batch: ProductionBatch
  step: StepNumber
  /** Only a draft step the user may edit is autosaved (never a finished one). */
  enabled: boolean
  values: V
  setValues(values: V): void
  /** Form values from the server copy. */
  fromBatch(batch: ProductionBatch): V
  /** Draft body without `version`; invalid inputs are left out (the server keeps its value). */
  toPayload(values: V): Record<string, unknown>
  onSaved(batch: ProductionBatch): void
}

export function draftKey(batchId: string, step: StepNumber) {
  return `mc.draft.${batchId}.${step}`
}

function readDraft<V>(key: string): LocalDraft<V> | null {
  try {
    const raw = storage.get(key)
    return raw ? (JSON.parse(raw) as LocalDraft<V>) : null
  } catch {
    return null
  }
}

const json = (v: unknown) => JSON.stringify(v)

/**
 * Autosave for one production step (see docs/ARCHITECTURE.md, "Autosave"):
 * - debounced PATCH 1500 ms after the last change, sending the batch `version`;
 * - immediate `keepalive` flush when the page is hidden or closed (`visibilitychange`,
 *   `pagehide`, Telegram `deactivated`), so closing the Mini App doesn't lose the last input;
 * - every unsaved change is also kept in localStorage; on the next visit it's resent
 *   automatically when its base version still matches, otherwise the user is asked;
 * - `409 PRODUCTION_CONFLICT`: the user's values stay; they overwrite or take the server copy;
 * - a server copy changed elsewhere is adopted while nothing here is unsaved.
 */
export function useAutosaveDraft<V>(options: Options<V>) {
  const { batch, step, enabled, values } = options
  const key = draftKey(batch.id, step)
  const queryClient = useQueryClient()
  const opts = useRef(options)
  opts.current = options

  const [status, setStatus] = useState<SaveStatus>('idle')
  const [savedAt, setSavedAt] = useState<Date | null>(null)
  const [errorCode, setErrorCode] = useState<string | null>(null)
  const [conflict, setConflict] = useState<ProductionBatch | null>(null)
  const [restore, setRestore] = useState<LocalDraft<V> | null>(null)

  // The server copy these values are based on, as far as this screen knows.
  const version = useRef(batch.version)
  const savedPayload = useRef(json(options.toPayload(options.fromBatch(batch))))
  const baseline = useRef(json(options.fromBatch(batch)))
  const latest = useRef(values)
  latest.current = values
  const inflight = useRef<Promise<unknown> | null>(null)
  const timer = useRef<number>()
  const conflictRef = useRef<ProductionBatch | null>(null)
  const resendNow = useRef(false)

  // Everything below reads refs, so these helpers can be recreated freely.
  const payloadKey = (v: V) => json(opts.current.toPayload(v))
  const isDirty = () =>
    payloadKey(latest.current) !== savedPayload.current || json(latest.current) !== baseline.current

  const writeDraft = () => {
    const draft: LocalDraft<V> = {
      values: latest.current,
      baseVersion: version.current,
      savedAt: Date.now(),
    }
    storage.set(key, json(draft))
  }

  const adopt = (server: ProductionBatch) => {
    const v = opts.current.fromBatch(server)
    version.current = server.version
    savedPayload.current = json(opts.current.toPayload(v))
    baseline.current = json(v)
    opts.current.setValues(v)
  }

  const schedule = (delay: number) => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => void save(), delay)
  }

  /** A save (normal or keepalive) went through with the `sent` values. */
  const applySaved = (server: ProductionBatch, sent: V) => {
    version.current = server.version
    savedPayload.current = payloadKey(sent)
    baseline.current = json(sent)
    opts.current.onSaved(server)
    setErrorCode(null)
    if (json(latest.current) === json(sent)) {
      storage.remove(key)
      setStatus('saved')
      setSavedAt(new Date())
    } else {
      // Typed more while saving: keep the backup current and save again.
      writeDraft()
      schedule(AUTOSAVE_DELAY_MS)
    }
  }

  const onConflict = (server: ProductionBatch) => {
    conflictRef.current = server
    setConflict(server)
    setStatus('conflict')
  }

  const save = async (): Promise<boolean> => {
    window.clearTimeout(timer.current)
    while (inflight.current) await inflight.current.catch(() => undefined)
    if (conflictRef.current) return false
    if (!opts.current.enabled) return true
    const sent = latest.current
    if (payloadKey(sent) === savedPayload.current) {
      if (json(sent) === baseline.current) storage.remove(key)
      return true
    }
    if (!navigator.onLine) {
      setStatus('offline')
      return false
    }
    setStatus('saving')
    const { batch: b, step: s } = opts.current
    const request = api.patch<ProductionBatch>(`/production/${b.id}/${slugOf(s)}`, {
      ...opts.current.toPayload(sent),
      version: version.current,
    })
    inflight.current = request
    try {
      const { data } = await request
      applySaved(data, sent)
      return true
    } catch (err) {
      const { code, details } = getError(err)
      if (code === 'PRODUCTION_CONFLICT' && details.batch) {
        onConflict(details.batch as ProductionBatch)
      } else if (code === 'NETWORK_ERROR') {
        setStatus('offline')
      } else if (axios.isAxiosError(err) && (err.response?.status ?? 0) >= 500) {
        setStatus('retrying')
        schedule(RETRY_DELAY_MS)
      } else {
        // The step no longer takes drafts (finished, cancelled, …): show it as it is now.
        setErrorCode(code)
        setStatus('failed')
        storage.remove(key)
        void queryClient.invalidateQueries({ queryKey: productionKeys.batch(b.id) })
      }
      return false
    } finally {
      inflight.current = null
    }
  }

  /** Page hidden or closing: send now with keepalive, so it survives the Mini App closing. */
  const flushKeepalive = () => {
    if (!opts.current.enabled || conflictRef.current) return
    const sent = latest.current
    if (payloadKey(sent) === savedPayload.current) return
    window.clearTimeout(timer.current)
    writeDraft()
    const { batch: b, step: s } = opts.current
    const request: Promise<void> = keepaliveSave(b.id, slugOf(s), {
      ...opts.current.toPayload(sent),
      version: version.current,
    })
      .then(async (r) => {
        const body = await r.json().catch(() => null)
        if (r.ok && body) applySaved(body as ProductionBatch, sent)
        else if (body?.error?.code === 'PRODUCTION_CONFLICT') onConflict(body.error.details.batch)
      })
      .catch(() => undefined) // offline, or the page is gone: the local backup is resent later
      .finally(() => {
        if (inflight.current === request) inflight.current = null
      })
    inflight.current = request
  }

  // The event listeners always call the latest versions.
  const handlers = useRef({ save, flushKeepalive, isDirty })
  handlers.current = { save, flushKeepalive, isDirty }

  // 1. On open: a local backup that isn't on the server yet is resent, or offered for restore.
  useEffect(() => {
    const draft = readDraft<V>(key)
    if (!draft) return
    const { batch: b, fromBatch, toPayload } = opts.current
    if (!enabled) {
      const data = stepData(b, step)
      if (b.status !== 'in_progress' || !data || data.status === 'finished') storage.remove(key)
      return
    }
    if (json(toPayload(draft.values)) === json(toPayload(fromBatch(b)))) {
      storage.remove(key) // already on the server (e.g. sent by the keepalive flush)
      return
    }
    const updatedAt = Date.parse(stepData(b, step)?.updated_at ?? b.updated_at)
    if (draft.baseVersion === b.version) {
      resendNow.current = true
      opts.current.setValues(draft.values)
    } else if (draft.savedAt > updatedAt) {
      setRestore(draft)
    } else {
      storage.remove(key) // older than what the server has
    }
  }, [key, enabled, step])

  // 2. Every change: back it up locally and schedule a save.
  useEffect(() => {
    if (!enabled || json(values) === baseline.current) return
    writeDraft()
    if (payloadKey(values) === savedPayload.current) return // only invalid / no-op edits
    setStatus('saving')
    schedule(resendNow.current ? 0 : AUTOSAVE_DELAY_MS)
    resendNow.current = false
  }, [values, enabled])

  // 3. The batch changed elsewhere (refetch, finish, reopen): adopt it if nothing is unsaved.
  useEffect(() => {
    if (batch.version === version.current || inflight.current || conflictRef.current) return
    if (!isDirty()) adopt(batch)
  }, [batch.version])

  // 4. Hidden / closed / back online.
  useEffect(() => {
    const flush = () => handlers.current.flushKeepalive()
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') flush()
      else if (handlers.current.isDirty()) void handlers.current.save()
    }
    const onOnline = () => {
      if (handlers.current.isDirty()) void handlers.current.save()
    }
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pagehide', flush)
    window.addEventListener('online', onOnline)
    telegram?.onEvent?.('deactivated', flush)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pagehide', flush)
      window.removeEventListener('online', onOnline)
      telegram?.offEvent?.('deactivated', flush)
    }
  }, [])

  // 5. Leaving the step (another step or page): save what's pending.
  useEffect(
    () => () => {
      window.clearTimeout(timer.current)
      if (opts.current.enabled && handlers.current.isDirty()) void handlers.current.save()
    },
    [],
  )

  /** Wait until everything typed is saved (before Finish). False if it couldn't be saved. */
  const flush = useCallback(async () => {
    const h = handlers.current
    if (!h.isDirty() && !inflight.current) return !conflictRef.current
    return h.save()
  }, [])

  /** Keep my values (overwrite the newer server copy), or take the server copy. */
  const resolveConflict = (keepMine: boolean) => {
    const server = conflictRef.current
    if (!server) return
    conflictRef.current = null
    setConflict(null)
    if (keepMine) {
      version.current = server.version
      savedPayload.current = json(opts.current.toPayload(opts.current.fromBatch(server)))
      opts.current.onSaved(server)
      void save()
    } else {
      adopt(server)
      opts.current.onSaved(server)
      storage.remove(key)
      setStatus('saved')
    }
  }

  const applyRestore = () => {
    if (!restore) return
    setRestore(null)
    opts.current.setValues(restore.values) // effect 2 saves it against the current version
  }

  const discardRestore = () => {
    setRestore(null)
    storage.remove(key)
  }

  return {
    status,
    savedAt,
    errorCode,
    conflict,
    /** Payload keys the server copy has changed (e.g. "weight_kg", "byproducts.liver"). */
    conflictFields: conflict
      ? diffKeys(
          JSON.parse(savedPayload.current) as Record<string, unknown>,
          options.toPayload(options.fromBatch(conflict)),
        )
      : [],
    resolveConflict,
    restore,
    applyRestore,
    discardRestore,
    flush,
    clearDraft: () => storage.remove(key),
    /** The batch version the next request must send. */
    version: () => version.current,
  }
}

function diffKeys(a: Record<string, unknown>, b: Record<string, unknown>): string[] {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)])
  const out: string[] = []
  for (const k of keys) {
    const av = a[k]
    const bv = b[k]
    if (av && bv && typeof av === 'object' && typeof bv === 'object') {
      for (const sub of diffKeys(av as Record<string, unknown>, bv as Record<string, unknown>)) {
        out.push(`${k}.${sub}`)
      }
    } else if (json(av) !== json(bv)) {
      out.push(k)
    }
  }
  return out
}
