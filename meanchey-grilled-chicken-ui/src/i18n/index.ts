import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import { storage } from '@/lib/storage'
import type { Language } from '@/lib/types'
import en from './locales/en.json'
import km from './locales/km.json'

const LANG_KEY = 'mc.language'
const saved = storage.get(LANG_KEY)
const initial: Language = saved === 'en' || saved === 'km' ? saved : 'km'

void i18n.use(initReactI18next).init({
  resources: { km: { translation: km }, en: { translation: en } },
  lng: initial,
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
})

document.documentElement.lang = initial

i18n.on('languageChanged', (lng) => {
  document.documentElement.lang = lng
  storage.set(LANG_KEY, lng)
})

export function setLanguage(lang: Language) {
  if (i18n.language !== lang) void i18n.changeLanguage(lang)
}

export default i18n
