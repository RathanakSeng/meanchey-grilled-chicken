// Fails if km.json and en.json don't have exactly the same keys.
import { readFileSync } from 'node:fs'

const load = (lang) =>
  JSON.parse(readFileSync(new URL(`../src/i18n/locales/${lang}.json`, import.meta.url), 'utf8'))

const flatten = (obj, prefix = '') =>
  Object.entries(obj).flatMap(([k, v]) =>
    v && typeof v === 'object' ? flatten(v, `${prefix}${k}.`) : [`${prefix}${k}`],
  )

const km = new Set(flatten(load('km')))
const en = new Set(flatten(load('en')))
const missingInKm = [...en].filter((k) => !km.has(k))
const missingInEn = [...km].filter((k) => !en.has(k))

if (missingInKm.length || missingInEn.length) {
  if (missingInKm.length) console.error('Missing in km.json:', missingInKm)
  if (missingInEn.length) console.error('Missing in en.json:', missingInEn)
  process.exit(1)
}
console.log(`i18n OK: ${km.size} keys in both languages`)
