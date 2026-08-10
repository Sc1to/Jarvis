import { useEffect, useState } from 'react'
import { getApps, createApp, deleteApp, restartApp } from '../api.js'

const EMPTY = { name: '', description: '', route: '', backend_port: '' }

export default function Apps() {
  const [apps, setApps] = useState([])
  const [form, setForm] = useState(EMPTY)
  const [error, setError] = useState(null)
  const [msg, setMsg] = useState(null)

  async function load() {
    try { setApps((await getApps()).data) } catch (e) { setError(e.message) }
  }

  useEffect(() => { load() }, [])

  async function submit(e) {
    e.preventDefault()
    setError(null)
    try {
      await createApp({ ...form, backend_port: Number(form.backend_port) })
      setForm(EMPTY)
      setMsg('App registered')
      load()
    } catch (e) {
      setError(e.response?.data?.detail ?? e.message)
    }
  }

  async function remove(id) {
    if (!confirm('Remove this app?')) return
    try { await deleteApp(id); load() } catch (e) { setError(e.message) }
  }

  async function restart(id) {
    try { await restartApp(id); setMsg('Restart triggered') } catch (e) { setError(e.message) }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold">Apps</h1>

      {error && <p className="text-red-400 text-sm">{error}</p>}
      {msg && <p className="text-green-400 text-sm">{msg}</p>}

      <form onSubmit={submit} className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
        <h2 className="text-sm font-medium text-gray-400">Register App</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <input className={input} placeholder="Name" value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))} required />
          <input className={input} placeholder="Description" value={form.description} onChange={e => setForm(f => ({...f, description: e.target.value}))} />
          <input className={input} placeholder="Route (e.g. /myapp)" value={form.route} onChange={e => setForm(f => ({...f, route: e.target.value}))} required />
          <input className={input} placeholder="Backend port" type="number" value={form.backend_port} onChange={e => setForm(f => ({...f, backend_port: e.target.value}))} required />
        </div>
        <button type="submit" className={btn}>Register</button>
      </form>

      <div className="space-y-2">
        {apps.length === 0 && <p className="text-gray-500 text-sm">No apps registered.</p>}
        {apps.map(a => (
          <div key={a.id} className="bg-gray-800 rounded-lg px-4 py-3 border border-gray-700 flex items-center gap-3">
            <div className="flex-1 min-w-0">
              <span className="text-sm font-medium">{a.name}</span>
              <span className="text-xs text-gray-500 ml-2">{a.route} → :{a.backend_port}</span>
              {a.description && <p className="text-xs text-gray-500 mt-0.5">{a.description}</p>}
            </div>
            <button onClick={() => restart(a.id)} className="text-xs text-blue-400 hover:text-blue-300">Restart</button>
            <button onClick={() => remove(a.id)} className="text-xs text-red-400 hover:text-red-300">Remove</button>
          </div>
        ))}
      </div>
    </div>
  )
}

const input = 'bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 w-full'
const btn = 'bg-blue-600 hover:bg-blue-500 text-white text-sm px-4 py-2 rounded'
