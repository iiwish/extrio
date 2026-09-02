import i18next, { type i18n as I18n } from 'i18next'
import { initReactI18next } from 'react-i18next'

import aiRunsEn from './locales/en/ai-runs.json'
import apiEn from './locales/en/api.json'
import appEn from './locales/en/app.json'
import authEn from './locales/en/auth.json'
import collectorDetailEn from './locales/en/collector-detail.json'
import collectorsEn from './locales/en/collectors.json'
import commonEn from './locales/en/common.json'
import homeEn from './locales/en/home.json'
import itemsEn from './locales/en/items.json'
import runsEn from './locales/en/runs.json'
import settingsEn from './locales/en/settings.json'
import aiRunsZh from './locales/zh/ai-runs.json'
import apiZh from './locales/zh/api.json'
import appZh from './locales/zh/app.json'
import authZh from './locales/zh/auth.json'
import collectorDetailZh from './locales/zh/collector-detail.json'
import collectorsZh from './locales/zh/collectors.json'
import commonZh from './locales/zh/common.json'
import homeZh from './locales/zh/home.json'
import itemsZh from './locales/zh/items.json'
import runsZh from './locales/zh/runs.json'
import settingsZh from './locales/zh/settings.json'
import { getStoredLanguage } from './language'

export const NAMESPACES = [
  'common',
  'app',
  'auth',
  'home',
  'collectors',
  'collectorDetail',
  'runs',
  'aiRuns',
  'items',
  'settings',
  'api',
] as const

export type Namespace = (typeof NAMESPACES)[number]

const resources = {
  zh: {
    common: commonZh,
    app: appZh,
    auth: authZh,
    home: homeZh,
    collectors: collectorsZh,
    collectorDetail: collectorDetailZh,
    runs: runsZh,
    aiRuns: aiRunsZh,
    items: itemsZh,
    settings: settingsZh,
    api: apiZh,
  },
  en: {
    common: commonEn,
    app: appEn,
    auth: authEn,
    home: homeEn,
    collectors: collectorsEn,
    collectorDetail: collectorDetailEn,
    runs: runsEn,
    aiRuns: aiRunsEn,
    items: itemsEn,
    settings: settingsEn,
    api: apiEn,
  },
} as const

export function initI18n(instance: I18n = i18next): I18n {
  if (!instance.isInitialized) {
    void instance.use(initReactI18next).init({
      lng: getStoredLanguage(),
      fallbackLng: 'zh',
      defaultNS: 'common',
      ns: NAMESPACES as unknown as string[],
      resources: resources as unknown as NonNullable<Parameters<I18n['init']>[0]>['resources'],
      interpolation: { escapeValue: false },
      react: { useSuspense: false },
    })
  }
  return instance
}

// Side-effect init: `import '@/i18n'` in main.tsx and vitest setup relies on this call.
initI18n()
