import i18next from 'i18next'

export const APP_LANGUAGES = [
  { code: 'zh', label: '中文' },
  { code: 'en', label: 'English' },
] as const

export type AppLanguage = (typeof APP_LANGUAGES)[number]['code']

const LANGUAGE_STORAGE_KEY = 'extrio.language'

export function isAppLanguage(value: string): value is AppLanguage {
  return APP_LANGUAGES.some((language) => language.code === value)
}

export function getStoredLanguage(): AppLanguage {
  try {
    const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY)
    if (stored && isAppLanguage(stored)) return stored
  } catch {
    // localStorage unavailable (privacy mode); fall through to default.
  }
  return 'zh'
}

export function getAppLanguage(): AppLanguage {
  const current = i18next.language
  return isAppLanguage(current) ? current : 'zh'
}

export function setAppLanguage(language: AppLanguage): void {
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, language)
  } catch {
    // Ignore persistence failures; the session still switches language.
  }
  void i18next.changeLanguage(language)
}
