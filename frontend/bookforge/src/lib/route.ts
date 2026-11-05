import { useEffect, useState } from 'react'

/** Hash routes, so the static files need no server-side fallback: #/series/<s>/<b>[/<tab>[/<id>]] */
export interface Route { series?: string; book?: string; tab?: string; id?: string }

export function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent)
  if (parts[0] !== 'series' || parts.length < 3) return {}
  return { series: parts[1], book: parts[2], tab: parts[3], id: parts.slice(4).join('/') || undefined }
}

export function href(r: Route): string {
  if (!r.series) return '#/'
  return '#/series/' + [r.series, r.book, r.tab, r.id].filter(Boolean).map((p) => encodeURIComponent(p as string)).join('/')
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash))
  useEffect(() => {
    const on = () => setRoute(parse(window.location.hash))
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return route
}
