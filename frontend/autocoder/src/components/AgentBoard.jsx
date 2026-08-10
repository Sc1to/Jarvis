import { useEffect, useState } from 'react'
import { getAgentsStatus, openSessionWs } from '../api'

const STATUS_META = {
  idle:      { label: 'Idle',      cls: 'bg-gray-700 text-gray-300',         dot: 'bg-gray-500' },
  active:    { label: 'Active',    cls: 'bg-blue-900/60 text-blue-200 ring-1 ring-blue-500', dot: 'bg-blue-400 animate-pulse' },
  completed: { label: 'Completed', cls: 'bg-green-900/60 text-green-200',     dot: 'bg-green-400' },
  failed:    { label: 'Failed',    cls: 'bg-red-900/60 text-red-200',         dot: 'bg-red-400' },
  parked:    { label: 'Parked',    cls: 'bg-amber-900/60 text-amber-200',     dot: 'bg-amber-400' },
}

function AgentCard({ agent }) {
  const meta = STATUS_META[agent.status] || STATUS_META.idle
  return (
    <div className={`rounded-xl p-4 flex flex-col gap-2 ${meta.cls}`}>
      <div className="flex items-center gap-2">
        <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${meta.dot}`} />
        <span className="font-semibold capitalize text-sm">{agent.agent_name}</span>
        <span className="ml-auto text-xs opacity-70">{meta.label}</span>
      </div>
      {agent.current_task && (
        <p className="text-xs opacity-60 line-clamp-2 leading-relaxed">{agent.current_task}</p>
      )}
    </div>
  )
}

export default function AgentBoard({ activeSessionId }) {
  const [agents, setAgents] = useState([])

  const refresh = () =>
    getAgentsStatus().then((r) => setAgents(r.data.data)).catch(() => {})

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    if (!activeSessionId) return
    const ws = openSessionWs(activeSessionId, (event) => {
      if (event.agent && event.status) {
        setAgents((prev) =>
          prev.map((a) =>
            a.agent_name === event.agent
              ? { ...a, status: event.status, current_task: event.current_task || a.current_task }
              : a
          )
        )
      }
    })
    return () => ws.close()
  }, [activeSessionId])

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4 text-gray-200">Agent Board</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {agents.map((a) => <AgentCard key={a.agent_name} agent={a} />)}
      </div>
    </div>
  )
}
