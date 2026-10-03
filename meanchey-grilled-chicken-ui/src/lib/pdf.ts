import axios from 'axios'
import { api } from './api'

/**
 * PDFs from the API (delivery notes, the Business info preview). They need the bearer token, so
 * they're fetched with the API client as a blob and shown from a blob: URL, never by linking to
 * the API directly.
 */

/** GET a PDF. Error bodies arrive as a Blob too: parse them so getError() sees the API code. */
export async function fetchPdf(url: string): Promise<Blob> {
  try {
    const { data } = await api.get<Blob>(url, { responseType: 'blob' })
    return data
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.data instanceof Blob) {
      try {
        err.response.data = JSON.parse(await err.response.data.text())
      } catch {
        /* not JSON: leave it */
      }
    }
    throw err
  }
}

const REVOKE_AFTER_MS = 60_000

function revokeLater(url: string) {
  window.setTimeout(() => URL.revokeObjectURL(url), REVOKE_AFTER_MS)
}

/** A mouse and a wide screen: a PC, where the browser's print dialog can print a PDF frame. */
export function isDesktop(): boolean {
  return window.matchMedia('(pointer: fine) and (min-width: 768px)').matches
}

/**
 * Call inside the click handler, before anything async: phones (and tablets) get a new tab right
 * away, so popup blockers (iOS Safari is strict) allow it; PCs print from a hidden frame instead
 * and get null.
 */
export function tabForPdf(): Window | null {
  return isDesktop() ? null : window.open('', '_blank')
}

/**
 * Show a PDF to print. With a `tab` (phones), the PDF opens there and the person prints or shares
 * it from the browser. Without one (PCs), it loads in a hidden frame and the print dialog opens;
 * if the browser can't print the frame, the PDF opens in a new tab instead.
 */
export async function printPdf(load: () => Promise<Blob>, tab: Window | null): Promise<void> {
  let blob: Blob
  try {
    blob = await load()
  } catch (err) {
    tab?.close()
    throw err
  }
  const url = URL.createObjectURL(blob)
  revokeLater(url)
  if (tab) {
    tab.location.href = url
    return
  }
  if (!isDesktop()) {
    // The tab was blocked: open the PDF here.
    window.location.assign(url)
    return
  }
  const frame = document.createElement('iframe')
  frame.setAttribute('aria-hidden', 'true')
  frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;'
  frame.src = url
  frame.onload = () => {
    try {
      frame.contentWindow?.focus()
      frame.contentWindow?.print()
    } catch {
      window.open(url, '_blank')
    }
    window.setTimeout(() => frame.remove(), REVOKE_AFTER_MS)
  }
  document.body.appendChild(frame)
}

/**
 * Open a PDF to look at, on any device (e.g. the Business info preview). `tab` comes from
 * `window.open('', '_blank')` inside the click handler; when it was blocked, the PDF opens here.
 */
export async function openPdf(load: () => Promise<Blob>, tab: Window | null): Promise<void> {
  let blob: Blob
  try {
    blob = await load()
  } catch (err) {
    tab?.close()
    throw err
  }
  const url = URL.createObjectURL(blob)
  revokeLater(url)
  if (tab) tab.location.href = url
  else window.location.assign(url)
}
