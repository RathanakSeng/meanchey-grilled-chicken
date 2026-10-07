import axios from 'axios'
import { useCallback, useEffect, useRef, useState } from 'react'
import { API_BASE_URL } from '@/lib/api'
import { getError } from '@/lib/errors'
import { storage, tokenStore } from '@/lib/storage'
import { telegram } from '@/lib/telegram'

export const AUTOSAVE_DELAY_MS = 1500
const RETRY_DELAY_MS = 5000

export type SaveStatus =
  | 'idle' // nothing typed yet
  | 'saving' // changes waiting for the debounce, or a request in flight
  | 'saved'
  | 'offline' // no connection: kept on this device, sent when back online
  | 'retrying' // the server failed; retried automatically
  | 'failed' // can't be saved any more (e.g. someone finished it): the record is reloaded
  | 'conflict' // someone else saved first: the user decides

/** What's kept in localStorage under the record's draft key. */
export interface LocalDraft<V> {
  values: V
  /** Server version the values were based on. */
  baseVersion: number
  savedAt: number
}

/** The record being edited and how to save it (production steps, preparations, …). */
export interface AutosaveTarget<E> {
  /** localStorage key of the local backup, e.g. `mc.draft.<batchId>.<step>`. */
  storageKey: string
  /** The current server copy. */
  entity: E
  version(entity: E): number
  /** When the server copy last changed (an older backup is dropped). */
  updatedAt(entity: E): string
  /** Still takes drafts on the server (a backup of something finished is dropped). */
  editable(entity: E): boolean
  /** The draft PATCH; resolves with the saved copy. */
  save(body: Record<string, unknown>): Promise<E>
  /** The same request with `keepalive` (fetch), for the page being hidden or closed. */
  keepalive(body: Record<string, unknown>): Promise<Response>
  /** The API's conflict code (`PRODUCTION_CONFLICT`, …) and where its details carry the copy. */
  conflictCode: string
  conflictEntity(details: Record<string, unknown>): E | undefined
  /** Refetch the record (after a save it no longer takes). */
  reload(): void
}

export interface AutosaveOptions<E, V> {
  target: AutosaveTarget<E>
  /** Only a draft the user may edit is autosaved. */
  enabled: boolean
  values: V
  setValues(values: V): void
  /** Form values from the server copy. */
  fromEntity(entity: E): V
  /** Draft body without `version`; invalid inputs are left out (the server keeps its value). */
  toPayload(values: V): Record<string, unknown>
  onSaved(entity: E): void
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
 * Autosave for a server-side draft (see docs/ARCHITECTURE.md, "Autosave"):
 * - debounced PATCH 1500 ms after the last change, sending the record's `version`;
 * - immediate `keepalive` flush when the page is hidden or closed (`visibilitychange`,
 *   `pagehide`, Telegram `deactivated`), so closing the Mini App doesn't lose the last input;
 * - every unsaved change is also kept in localStorage; on the next visit it's resent
 *   automatically when its base version still matches, otherwise the user is asked;
 * - a version conflict: the user's values stay; they overwrite or take the server copy;
 * - a server copy changed elsewhere is adopted while nothing here is unsaved.
 */
export function useAutosave<E, V>(options: AutosaveOptions<E, V>) {
  const { target, enabled, values } = options
  const key = target.storageKey
  const opts = useRef(options)
  opts.current = options

  const [status, setStatus] = useState<SaveStatus>('idle')
  const [savedAt, setSavedAt] = useState<Date | null>(null)
  const [errorCode, setErrorCode] = useState<string | null>(null)
  const [conflict, setConflict] = useState<E | null>(null)
  const [restore, setRestore] = useState<LocalDraft<V> | null>(null)

  // The server copy these values are based on, as far as this screen knows.
  const version = useRef(target.version(target.entity))
  const savedPayload = useRef(json(options.toPayload(options.fromEntity(target.entity))))
  const baseline = useRef(json(options.fromEntity(target.entity)))
  const latest = useRef(values)
  latest.current = values
  const inflight = useRef<Promise<unknown> | null>(null)
  const timer = useRef<number>()
  const conflictRef = useRef<E | null>(null)
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

  const adopt = (server: E) => {
    const v = opts.current.fromEntity(server)
    version.current = opts.current.target.version(server)
    savedPayload.current = json(opts.current.toPayload(v))
    baseline.current = json(v)
    opts.current.setValues(v)
  }

  const schedule = (delay: number) => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => void save(), delay)
  }

  /** A save (normal or keepalive) went through with the `sent` values. */
  const applySaved = (server: E, sent: V) => {
    version.current = opts.current.target.version(server)
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

  const onConflict = (server: E) => {
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
      // Typed back to what the server has: nothing to send, nothing pending.
      setStatus((s) => (s === 'saving' ? 'saved' : s))
      return true
    }
    if (!navigator.onLine) {
      setStatus('offline')
      return false
    }
    setStatus('saving')
    const t = opts.current.target
    const request = t.save({ ...opts.current.toPayload(sent), version: version.current })
    inflight.current = request
    try {
      applySaved(await request, sent)
      return true
    } catch (err) {
      const { code, details } = getError(err)
      const server = code === t.conflictCode ? t.conflictEntity(details) : undefined
      if (server) {
        onConflict(server)
      } else if (code === 'NETWORK_ERROR') {
        setStatus('offline')
      } else if (axios.isAxiosError(err) && (err.response?.status ?? 0) >= 500) {
        setStatus('retrying')
        schedule(RETRY_DELAY_MS)
      } else {
        // The record no longer takes drafts (finished, cancelled, …): show it as it is now.
        setErrorCode(code)
        setStatus('failed')
        storage.remove(key)
        t.reload()
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
    const t = opts.current.target
    const request: Promise<void> = t
      .keepalive({ ...opts.current.toPayload(sent), version: version.current })
      .then(async (r) => {
        const body = await r.json().catch(() => null)
        if (r.ok && body) applySaved(body as E, sent)
        else if (body?.error?.code === t.conflictCode) {
          const server = t.conflictEntity(body.error.details ?? {})
          if (server) onConflict(server)
        }
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
    const { target: t, fromEntity, toPayload } = opts.current
    if (!enabled) {
      if (!t.editable(t.entity)) storage.remove(key)
      return
    }
    if (json(toPayload(draft.values)) === json(toPayload(fromEntity(t.entity)))) {
      storage.remove(key) // already on the server (e.g. sent by the keepalive flush)
      return
    }
    const updatedAt = Date.parse(t.updatedAt(t.entity))
    if (draft.baseVersion === t.version(t.entity)) {
      resendNow.current = true
      opts.current.setValues(draft.values)
    } else if (draft.savedAt > updatedAt) {
      setRestore(draft)
    } else {
      storage.remove(key) // older than what the server has
    }
  }, [key, enabled])

  // 2. Every change: back it up locally and schedule a save.
  useEffect(() => {
    if (!enabled || json(values) === baseline.current) return
    writeDraft()
    if (payloadKey(values) === savedPayload.current) return // only invalid / no-op edits
    setStatus('saving')
    schedule(resendNow.current ? 0 : AUTOSAVE_DELAY_MS)
    resendNow.current = false
  }, [values, enabled])

  // 3. The record changed elsewhere (refetch, finish, reopen): adopt it if nothing is unsaved.
  const serverVersion = target.version(target.entity)
  useEffect(() => {
    if (serverVersion === version.current || inflight.current || conflictRef.current) return
    if (!isDirty()) adopt(opts.current.target.entity)
  }, [serverVersion])

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

  // 5. Leaving (another step or page): save what's pending.
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
      version.current = opts.current.target.version(server)
      savedPayload.current = json(opts.current.toPayload(opts.current.fromEntity(server)))
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
          options.toPayload(options.fromEntity(conflict)),
        )
      : [],
    resolveConflict,
    restore,
    applyRestore,
    discardRestore,
    flush,
    clearDraft: () => storage.remove(key),
    /** The version the next request must send. */
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

/**
 * A draft save that survives the page being hidden or closed (`keepalive`). Axios can't send
 * keepalive requests, so this uses fetch with the same bearer token. A 401 here isn't
 * refreshed; the local backup covers it and is resent on the next visit.
 */
export function keepaliveFetch(path: string, method: string, body: object): Promise<Response> {
  const token = tokenStore.getAccess()
  return fetch(`${API_BASE_URL}${path}`, {
    method,
    keepalive: true,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  })
}
