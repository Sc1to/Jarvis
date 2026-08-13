import { useEffect, useState } from 'react'
import { getUpdates, applyUpdates, gitPull, restartService, deployService, getHealthCheck } from '../api.js'

const SERVICES = ['admin', 'chat', 'writer', 'coding', 'trading', 'autocoder']

function fmtChecked(iso) {
  if (!iso) return null
  const d = new Date(iso + 'Z')
  const mins = Math.round((Date.now() - d.getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return d.toLocaleDateString()
}

export default function Updates() {
  const [data, setData] = useState(null)
  const [applying, setApplying] = useState(false)
  const [checking, setChecking] = useState(false)
  const [pulling, setPulling] = useState(false)
  const [pullResult, setPullResult] = useState(null)
  const [restarting, setRestarting] = useState(null)
  const [restartPolling, setRestartPolling] = useState(false)
  const [restartMsg, setRestartMsg] = useState(null)
  const [deploying, setDeploying] = useState(false)
  const [deployPolling, setDeployPolling] = useState(false)
  const [deployMsg, setDeployMsg] = useState(null)
  const [msg, setMsg] = useState(null)
  const [error, setError] = useState(null)

  async function load() {
    setChecking(true)
    try {
      const r = await getUpdates()
      setData(r.data)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setChecking(false)
    }
  }

  useEffect(() => { load() }, [])

  async function apply() {
    if (!confirm(`Apply ${data?.count} package update(s)?`)) return
    setApplying(true)
    setError(null)
    try {
      const r = await applyUpdates()
      setMsg(r.data.message)
    } catch (e) {
      setError(e.response?.data?.detail ?? e.message)
    } finally {
      setApplying(false)
    }
  }

  async function pull() {
    setPulling(true)
    setPullResult(null)
    setError(null)
    try {
      const r = await gitPull()
      setPullResult({ ok: true, text: r.data.output || 'Already up to date.' })
    } catch (e) {
      setPullResult({ ok: false, text: e.response?.data?.detail ?? e.message })
    } finally {
      setPulling(false)
    }
  }

  // Poll /health-check until target service(s) report ok, or 60s elapses.
  async function pollHealth(appName, setPolling, setMsg) {
    setPolling(true)
    // Let the service begin shutting down before the first check.
    await new Promise(r => setTimeout(r, 2000))

    const deadline = Date.now() + 60_000
    const label = appName === 'all' ? 'All services' : appName

    while (Date.now() < deadline) {
      try {
        const r = await getHealthCheck()
        const all = r.data  // [{name, health: {status}}, ...]

        // admin is never in the apps table — the health-check responding at
        // all means admin is up (it IS the server that handles this request).
        if (appName === 'admin') {
          setMsg({ ok: true, text: '✓ admin is up and running' })
          setPolling(false)
          return
        }

        const targets = appName === 'all'
          ? all.filter(s => s.health !== null)
          : all.filter(s => s.name === appName)

        if (targets.length > 0 && targets.every(s => s.health?.status === 'ok')) {
          setMsg({ ok: true, text: `✓ ${label} ${appName === 'all' ? 'are' : 'is'} up and running` })
          setPolling(false)
          return
        }
      } catch {
        // API down (admin restarting) — keep trying
      }
      await new Promise(r => setTimeout(r, 3000))
    }

    setMsg({ ok: false, text: `${label} didn't respond within 60s — check the dashboard` })
    setPolling(false)
  }

  async function deploy() {
    setDeploying(true)
    setDeployMsg(null)
    setDeployPolling(false)
    try {
      await deployService('all')
      pollHealth('all', setDeployPolling, setDeployMsg)
    } catch (e) {
      setDeployMsg({ ok: false, text: `Error: ${e.response?.data?.detail ?? e.message}` })
    } finally {
      setDeploying(false)
    }
  }

  async function restart(app) {
    setRestarting(app)
    setRestartMsg(null)
    setRestartPolling(false)
    try {
      await restartService(app)
      pollHealth(app, setRestartPolling, setRestartMsg)
    } catch (e) {
      setRestartMsg({ ok: false, text: `Error: ${e.response?.data?.detail ?? e.message}` })
    } finally {
      setRestarting(null)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Updates</h1>
        <button onClick={load} disabled={checking} className="text-xs text-gray-400 hover:text-white disabled:opacity-40">
          {checking ? 'Checking…' : 'Refresh'}
        </button>
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}
      {msg && <p className="text-green-400 text-sm">{msg}</p>}
      {data?.error && <p className="text-yellow-400 text-sm">Check failed: {data.error}</p>}

      {/* Git pull */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium">Code</p>
          <button
            onClick={pull}
            disabled={pulling}
            className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs px-3 py-1.5 rounded"
          >
            {pulling ? 'Pulling…' : 'git pull'}
          </button>
        </div>
        {pullResult && (
          <pre className={`text-xs font-mono whitespace-pre-wrap ${pullResult.ok ? 'text-green-400' : 'text-red-400'}`}>
            {pullResult.text}
          </pre>
        )}
      </div>

      {/* Service restarts */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium">Services</p>
          <div className="flex gap-2">
            <button
              onClick={deploy}
              disabled={deploying || deployPolling || !!restarting || restartPolling}
              className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs px-3 py-1.5 rounded"
            >
              {deploying ? 'Deploying…' : 'Deploy all'}
            </button>
            <button
              onClick={() => restart('all')}
              disabled={deploying || deployPolling || !!restarting || restartPolling}
              className="bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white text-xs px-3 py-1.5 rounded"
            >
              {restarting === 'all' ? 'Restarting…' : 'Restart all'}
            </button>
          </div>
        </div>
        {deployPolling && (
          <p className="text-xs text-yellow-400">Waiting for services to come back up…</p>
        )}
        {deployMsg && (
          <p className={`text-xs ${deployMsg.ok ? 'text-green-400' : 'text-red-400'}`}>
            {deployMsg.text}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          {SERVICES.map(svc => (
            <button
              key={svc}
              onClick={() => restart(svc)}
              disabled={deploying || deployPolling || !!restarting || restartPolling}
              className="bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white text-xs px-3 py-1.5 rounded"
            >
              {restarting === svc ? 'Restarting…' : svc}
            </button>
          ))}
        </div>
        {restartPolling && (
          <p className="text-xs text-yellow-400">Waiting for service to come back up…</p>
        )}
        {restartMsg && (
          <p className={`text-xs ${restartMsg.ok ? 'text-green-400' : 'text-red-400'}`}>
            {restartMsg.text}
          </p>
        )}
      </div>

      {/* Apt updates */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm">
            <span className="text-gray-400">Pending packages: </span>
            <span className={data?.count > 0 ? 'text-yellow-400 font-medium' : 'text-green-400'}>
              {data?.count ?? '—'}
            </span>
          </p>
          {data?.last_checked && (
            <p className="text-xs text-gray-500">Checked {fmtChecked(data.last_checked)}</p>
          )}
        </div>

        {data?.count > 0 && (
          <>
            <div className="max-h-48 overflow-y-auto space-y-1">
              {data.packages.map((pkg, i) => (
                <p key={i} className="text-xs font-mono text-gray-400">{pkg}</p>
              ))}
            </div>
            <button
              onClick={apply}
              disabled={applying}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm px-4 py-2 rounded"
            >
              {applying ? 'Applying...' : 'Apply updates'}
            </button>
          </>
        )}

        {data?.count === 0 && (
          <p className="text-sm text-green-400">System is up to date.</p>
        )}
      </div>

      <p className="text-xs text-gray-500">
        Updates are blocked while an autocoder session is active. Package check runs in the background — refresh to see results.
      </p>
    </div>
  )
}
