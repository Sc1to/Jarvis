import { useEffect, useState } from 'react'
import { getSession, getSessionLog, getProjectCommits, getCommitDiff, getSessions } from '../api'

function CommitRow({ projectId, commit }) {
  const [diff, setDiff] = useState(null)
  const [open, setOpen] = useState(false)

  const toggle = async () => {
    if (!open && !diff) {
      const r = await getCommitDiff(projectId, commit.hash).catch(() => null)
      if (r) setDiff(r.data.data.diff)
    }
    setOpen((p) => !p)
  }

  return (
    <div className="border border-gray-800 rounded-lg overflow-hidden">
      <button
        className="w-full text-left px-4 py-2 flex items-center gap-3 hover:bg-gray-800/40 text-sm"
        onClick={toggle}
      >
        <span className="font-mono text-gray-500 text-xs w-16 flex-shrink-0">{commit.hash.slice(0, 7)}</span>
        <span className="text-gray-200 flex-1">{commit.message}</span>
        <span className="text-gray-600 text-xs flex-shrink-0">{new Date(commit.timestamp).toLocaleTimeString()}</span>
        <span className="text-gray-600 text-xs">{open ? '▲' : '▼'}</span>
      </button>
      {open && diff && (
        <pre className="text-xs text-gray-400 px-4 pb-3 overflow-x-auto">{diff}</pre>
      )}
    </div>
  )
}

export default function MorningReview() {
  const [sessions, setSessions] = useState([])
  const [selected, setSelected] = useState(null)
  const [session, setSession] = useState(null)
  const [events, setEvents] = useState([])
  const [commits, setCommits] = useState([])

  useEffect(() => {
    getSessions().then((r) => {
      const list = r.data.data
      setSessions(list)
      if (list.length > 0) setSelected(list[0].id)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!selected) return
    Promise.all([
      getSession(selected),
      getSessionLog(selected),
    ]).then(([sr, lr]) => {
      setSession(sr.data.data)
      setEvents(lr.data.data)
      if (sr.data.data.project_id) {
        getProjectCommits(sr.data.data.project_id)
          .then((r) => setCommits(r.data.data))
          .catch(() => {})
      } else {
        setCommits([])
      }
    }).catch(() => {})
  }, [selected])

  if (!session) return <p className="text-gray-600 text-sm p-4">No sessions yet.</p>

  const duration = session.closed_at
    ? Math.round((new Date(session.closed_at) - new Date(session.started_at)) / 60000)
    : null

  const agentSections = {}
  events.forEach((e) => {
    if (!agentSections[e.agent]) agentSections[e.agent] = []
    agentSections[e.agent].push(e)
  })

  const parkedEvent = events.find((e) => e.event_type === 'parked')
  const issues = events.filter((e) => e.event_type === 'failure')

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-gray-200">Morning Review</h2>
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

      {/* Summary card */}
      <div className="bg-gray-900 rounded-xl p-5 space-y-2">
        <div className="flex items-center gap-3">
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
            session.outcome === 'success' ? 'bg-green-900 text-green-300' :
            session.outcome === 'parked'  ? 'bg-amber-900 text-amber-300' :
                                            'bg-red-900 text-red-300'
          }`}>
            {session.outcome || session.status}
          </span>
          <span className="text-gray-400 text-sm">{session.description}</span>
          {duration !== null && (
            <span className="ml-auto text-gray-600 text-xs">{duration} min</span>
          )}
        </div>
        <p className="text-gray-600 text-xs">
          {new Date(session.started_at).toLocaleString()}
          {session.closed_at && ` → ${new Date(session.closed_at).toLocaleString()}`}
        </p>
      </div>

      {/* Parked explanation */}
      {parkedEvent && (
        <div className="bg-amber-950/40 border border-amber-800/50 rounded-xl p-4">
          <h3 className="text-amber-300 font-medium text-sm mb-2">Session Parked</h3>
          <p className="text-amber-200/80 text-sm">{parkedEvent.content}</p>
        </div>
      )}

      {/* Per-agent sections */}
      <div>
        <h3 className="text-gray-400 text-sm font-medium mb-3">Agent Activity</h3>
        <div className="space-y-3">
          {Object.entries(agentSections).map(([agent, agentEvents]) => (
            <div key={agent} className="bg-gray-900 rounded-xl p-4">
              <h4 className="font-medium text-sm capitalize text-gray-300 mb-2">{agent}</h4>
              <ul className="space-y-1">
                {agentEvents.map((e, idx) => (
                  <li key={idx} className={`text-xs ${
                    e.event_type === 'failure' ? 'text-red-400' :
                    e.event_type === 'task_complete' ? 'text-green-400' :
                    'text-gray-500'
                  }`}>
                    {e.content || e.event_type}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>

      {/* Commits */}
      {commits.length > 0 && (
        <div>
          <h3 className="text-gray-400 text-sm font-medium mb-3">Commits ({commits.length})</h3>
          <div className="space-y-2">
            {commits.map((c) => (
              <CommitRow key={c.hash} projectId={session.project_id} commit={c} />
            ))}
          </div>
        </div>
      )}

      {/* Open issues */}
      {issues.length > 0 && (
        <div>
          <h3 className="text-gray-400 text-sm font-medium mb-3">Failures / Issues ({issues.length})</h3>
          <ul className="space-y-2">
            {issues.map((e, idx) => (
              <li key={idx} className="bg-red-950/30 border border-red-900/40 rounded-lg p-3 text-red-300 text-sm">
                <span className="text-red-500 text-xs capitalize mr-2">{e.agent}</span>
                {e.content}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
