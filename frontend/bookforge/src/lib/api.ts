const BASE = `${import.meta.env.BASE_URL}api`

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message) }
}

export async function api<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  let res: Response
  try {
    res = await fetch(BASE + path, {
      method: init?.method ?? 'GET',
      headers: init?.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
    })
  } catch (e) {
    throw new ApiError(`Cannot reach the Bookforge service (${String(e)})`, 0)
  }
  let body: any = null
  try { body = await res.json() } catch { /* not JSON */ }
  if (!res.ok || body?.status === 'error') {
    throw new ApiError(body?.detail ?? `HTTP ${res.status}`, res.status)
  }
  return body.data as T
}

export const post = <T>(path: string, body?: unknown) => api<T>(path, { method: 'POST', body: body ?? {} })

export const del = <T>(path: string) => api<T>(path, { method: 'DELETE' })
export const bookPath = (series: string, book: string) => `/series/${encodeURIComponent(series)}/books/${encodeURIComponent(book)}`
