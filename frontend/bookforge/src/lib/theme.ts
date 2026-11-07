import { useEffect, useState } from 'react'

export type ThemeMode = 'system' | 'light' | 'dark'
const KEY = 'bookforge-theme'
const dark = () => window.matchMedia('(prefers-color-scheme: dark)')

/** The saved choice; storage can be blocked (private window), so a failure means "follow the system". */
export function savedMode(): ThemeMode {
  try { const v = localStorage.getItem(KEY); if (v === 'light' || v === 'dark') return v } catch { /* blocked */ }
  return 'system'
}

export function applyMode(mode: ThemeMode) {
  const on = mode === 'dark' || (mode === 'system' && dark().matches)
  document.documentElement.classList.toggle('dark', on)
}

export function useTheme(): [ThemeMode, (m: ThemeMode) => void] {
  const [mode, setMode] = useState<ThemeMode>(savedMode)
  useEffect(() => {
    applyMode(mode)
    if (mode !== 'system') return
    const q = dark()
    const follow = () => applyMode('system')
    q.addEventListener('change', follow)
    return () => q.removeEventListener('change', follow)
  }, [mode])
  const set = (m: ThemeMode) => {
    try { if (m === 'system') localStorage.removeItem(KEY); else localStorage.setItem(KEY, m) } catch { /* blocked: applies for this visit only */ }
    setMode(m)
  }
  return [mode, set]
}
