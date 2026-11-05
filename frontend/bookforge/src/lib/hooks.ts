import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'

export interface Loaded<T> { data: T | null; error: string | null; loading: boolean; reload: () => void }

/** Fetch `path` (null = do nothing), reload when it changes, and every `pollMs` if given. */
export function useApi<T>(path: string | null, pollMs?: number): Loaded<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(path !== null)
  const [tick, setTick] = useState(0)
  const current = useRef(path)
  current.current = path

  useEffect(() => {
    if (path === null) { setData(null); setLoading(false); return }
    let alive = true
    api<T>(path)
      .then((d) => { if (alive && current.current === path) { setData(d); setError(null) } })
      .catch((e) => { if (alive) setError(e.message) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [path, tick])

  useEffect(() => {
    if (!pollMs || path === null) return
    const t = setInterval(() => setTick((n) => n + 1), pollMs)
    return () => clearInterval(t)
  }, [pollMs, path])

  const reload = useCallback(() => setTick((n) => n + 1), [])
  return { data, error, loading, reload }
}

/** Run an action that can fail; remembers the error and whether it is running. */
export function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = useCallback(async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null)
    try { await fn(); return true } catch (e: any) { setError(e.message ?? String(e)); return false } finally { setBusy(false) }
  }, [])
  return { busy, error, run, clear: () => setError(null) }
}

/** Start a background job (a POST that answers 202 with the job) and follow it until it ends. */
export function useJob<T = any>(base: string) {
  const [state, setState] = useState<{ result: T | null; error: string | null; busy: boolean }>({ result: null, error: null, busy: false })
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const run = useCallback(async (path: string, body?: unknown) => {
    setState({ result: null, error: null, busy: true })
    try {
      let job = await api<{ id: string; status: string; result: T | null; error: string | null }>(base + path, { method: 'POST', body: body ?? {} })
      while (job.status === 'running') {
        await new Promise((r) => setTimeout(r, 1500))
        if (!alive.current) return
        job = await api(`${base}/jobs/${job.id}`)
      }
      if (!alive.current) return
      if (job.status === 'done') setState({ result: job.result, error: null, busy: false })
      else setState({ result: null, error: job.error ?? job.status, busy: false })
    } catch (e: any) {
      if (alive.current) setState({ result: null, error: e.message ?? String(e), busy: false })
    }
  }, [base])
  return { ...state, run, reset: () => setState({ result: null, error: null, busy: false }) }
}
