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
