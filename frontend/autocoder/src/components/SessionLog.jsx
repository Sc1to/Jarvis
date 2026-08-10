import { useEffect, useRef, useState } from 'react'
import { getSessionLog, getSessions, openSessionWs } from '../api'

const TYPE_CLS = {
  failure:  'text-red-400',
  parked:   'text-amber-400',
  internet_access: 'text-gray-500',
}

function LogEntry({ event }) {
  const [open, setOpen] = useState(false)
  const cls = TYPE_CLS[event.event_type] || 'text-gray-200'
  const isExpandable = event.event_type === 'parked' || event.event_type === 'internet_access'

  return (
    <div className="font-mono text-sm border-b border-gray-800 last:border-0">
      <button
        className={`w-full text-left px-4 py-2 flex gap-3 hover:bg-gray-800/40 ${isExpandable ? 'cursor-pointer' : 'cursor-default'}`}
        onClick={() => isExpandable && setOpen((p) => !p)}
      >
        <span className="text-gray-600 flex-shrink-0 w-20 text-xs pt-0.5">
          {event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : ''}
        </span>
        <span className="text-gray-500 w-24 flex-shrink-0 capitalize text-xs pt-0.5">{event.agent}</span>
        <span className={cls}>{event.content || event.event_type}</span>
        {isExpandable && (
          <span className="ml-auto text-gray-600 text-xs">{open ? '▲' : '▼'}</span>
        )}
      </button>
      {open && event.content && (
        <div className="px-4 pb-3 pl-28 text-xs text-gray-400 whitespace-pre-wrap">{event.content}</div>
      )}
    </div>
  )
}

export default function SessionLog() {
  const [sessions, setSessions] = useState([])
  const [selected, setSelected] = useState(null)
  const [events, setEvents] = useState([])
  const wsRef = useRef(null)
  const bottomRef = useRef(null)

  useEffect(() => {
    getSessions().then((r) => {
      const list = r.data.data
      setSessions(list)
      if (list.length > 0 && !selected) setSelected(list[0].id)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!selected) return
    getSessionLog(selected).then((r) => setEvents(r.data.data)).catch(() => {})

    if (wsRef.current) wsRef.current.close()
    wsRef.current = openSessionWs(selected, (event) => {
      if (event.event_type) {
        setEvents((prev) => [...prev, event])
        setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
      }
    })
    return () => wsRef.current?.close()
  }, [selected])

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 mb-4">
        <h2 className="text-lg font-semibold text-gray-200">Session Log</h2>
        <select
          className="ml-auto bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200"
          value={selected || ''}
          onChange={(e) => setSelected(e.target.value)}
        >
          {sessions.map((s) => (
            <option key={s.id} value={s.id}>
              {new Date(s.started_at).toLocaleDateString()} — {s.description?.slice(0, 40) || s.id.slice(0, 8)}
            </option>
          ))}
        </select>
      </div>

      <div className="flex-1 overflow-y-auto bg-gray-900 rounded-xl">
        {events.length === 0 ? (
          <p className="text-gray-600 text-sm p-6">No events yet.</p>
        ) : (
          events.map((e) => <LogEntry key={e.id || e.timestamp} event={e} />)
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
