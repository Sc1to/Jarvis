import type { ReactNode } from 'react'
import type { Status } from '../lib/types'

export const STATUS_STYLE: Record<string, { dot: string; chip: string; label: string }> = {
  accepted: { dot: 'bg-emerald-500', chip: 'bg-emerald-100 text-emerald-800', label: 'accepted' },
  flagged: { dot: 'bg-red-500', chip: 'bg-red-100 text-red-800', label: 'flagged' },
  stale: { dot: 'bg-amber-500', chip: 'bg-amber-100 text-amber-900', label: 'stale' },
  pending: { dot: 'bg-slate-300', chip: 'bg-slate-100 text-slate-600', label: 'pending' },
  drafted: { dot: 'bg-sky-400', chip: 'bg-sky-100 text-sky-800', label: 'drafted' },
  checked: { dot: 'bg-sky-500', chip: 'bg-sky-100 text-sky-800', label: 'checked' },
}

export function StatusBadge({ status }: { status: Status | string }) {
  const s = STATUS_STYLE[status] ?? STATUS_STYLE.pending
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${s.chip}`}>{s.label}</span>
}

export function Dot({ status, title }: { status: Status | string; title?: string }) {
  const s = STATUS_STYLE[status] ?? STATUS_STYLE.pending
  return <span title={title ?? status} className={`inline-block h-3 w-3 shrink-0 rounded-full ${s.dot}`} />
}

export function Card({ title, children, right, tone }: { title?: ReactNode; children: ReactNode; right?: ReactNode; tone?: 'warn' }) {
  return (
    <section className={`rounded-lg border bg-white p-3 sm:p-4 ${tone === 'warn' ? 'border-amber-300 bg-amber-50' : 'border-slate-200'}`}>
      {(title || right) && (
        <div className="mb-2 flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          {right}
        </div>
      )}
      {children}
    </section>
  )
}

export function ErrorBanner({ message, onClose }: { message: string | null; onClose?: () => void }) {
  if (!message) return null
  return (
    <div role="alert" className="flex items-start justify-between gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
      <span className="break-words">{message}</span>
      {onClose && <button onClick={onClose} className="shrink-0 font-medium" aria-label="Dismiss">×</button>}
    </div>
  )
}

export function Loading({ what = 'Loading' }: { what?: string }) {
  return <p className="p-3 text-sm text-slate-500">{what}…</p>
}

type BtnProps = { children: ReactNode; onClick?: () => void; disabled?: boolean; kind?: 'primary' | 'plain' | 'danger'; type?: 'button' | 'submit'; title?: string }

export function Button({ children, onClick, disabled, kind = 'plain', type = 'button', title }: BtnProps) {
  const styles = {
    primary: 'bg-slate-900 text-white hover:bg-slate-700',
    plain: 'border border-slate-300 bg-white text-slate-800 hover:bg-slate-50',
    danger: 'border border-red-300 bg-white text-red-700 hover:bg-red-50',
  }[kind]
  return (
    <button type={type} title={title} onClick={onClick} disabled={disabled}
      className={`min-h-10 rounded-md px-3 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${styles}`}>
      {children}
    </button>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-slate-300 p-4 text-center text-sm text-slate-500">{children}</p>
}

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  const rx = /(\*\*[^*]+\*\*|`[^`]+`)/g
  let last = 0
  for (const m of text.matchAll(rx)) {
    if (m.index! > last) out.push(text.slice(last, m.index))
    const tok = m[0]
    out.push(tok.startsWith('**')
      ? <strong key={m.index}>{tok.slice(2, -2)}</strong>
      : <code key={m.index} className="rounded bg-slate-100 px-1 text-[0.85em]">{tok.slice(1, -1)}</code>)
    last = m.index! + tok.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

/** A small Markdown renderer for reports and manuscripts: headings, lists, quotes, bold, code. Never injects HTML. */
export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = []
  let list: string[] = []
  let para: string[] = []
  const flushList = () => { if (list.length) { blocks.push(<ul key={blocks.length} className="my-2 list-disc space-y-1 pl-5">{list.map((l, i) => <li key={i}>{inline(l)}</li>)}</ul>); list = [] } }
  const flushPara = () => { if (para.length) { blocks.push(<p key={blocks.length} className="my-2">{inline(para.join(' '))}</p>); para = [] } }
  for (const line of text.split('\n')) {
    const h = /^(#{1,3})\s+(.*)$/.exec(line)
    if (h) {
      flushList(); flushPara()
      const cls = ['text-xl font-semibold mt-4', 'text-lg font-semibold mt-4', 'text-base font-semibold mt-3'][h[1].length - 1]
      blocks.push(<div key={blocks.length} role="heading" aria-level={h[1].length} className={cls}>{inline(h[2])}</div>)
    } else if (/^\s*[-*]\s+/.test(line) && !/^\*\s\*\s\*$/.test(line.trim())) {
      flushPara(); list.push(line.replace(/^\s*[-*]\s+/, ''))
    } else if (/^>\s?/.test(line)) {
      flushList(); flushPara()
      blocks.push(<blockquote key={blocks.length} className="my-1 border-l-4 border-slate-300 pl-3 text-slate-600">{inline(line.replace(/^>\s?/, ''))}</blockquote>)
    } else if (/^\*\s\*\s\*$/.test(line.trim())) {
      flushList(); flushPara(); blocks.push(<hr key={blocks.length} className="my-6 border-slate-300" />)
    } else if (!line.trim()) {
      flushList(); flushPara()
    } else {
      flushList(); para.push(line.trim())
    }
  }
  flushList(); flushPara()
  return <div className="text-sm leading-relaxed text-slate-800 [overflow-wrap:anywhere]">{blocks}</div>
}

export function fmtTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })
}
