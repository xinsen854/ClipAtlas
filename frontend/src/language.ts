import { useSyncExternalStore } from 'react'

export type Language = 'zh' | 'en'

const STORAGE_KEY = 'clipatlas.language'
let current: Language = 'zh'
const listeners = new Set<() => void>()

if (typeof window !== 'undefined') {
  current = window.localStorage.getItem(STORAGE_KEY) === 'en' ? 'en' : 'zh'
}

export function getLanguage(): Language {
  return current
}

export function setLanguage(language: Language): void {
  if (current === language) return
  current = language
  if (typeof window !== 'undefined') window.localStorage.setItem(STORAGE_KEY, language)
  listeners.forEach((listener) => listener())
}

export function subscribeLanguage(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useLanguage(): Language {
  return useSyncExternalStore(subscribeLanguage, getLanguage, () => 'zh')
}
