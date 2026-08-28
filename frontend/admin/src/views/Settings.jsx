import { useEffect, useState } from 'react'

const API = import.meta.env.VITE_API_URL ?? ''

export default function Settings() {
  const [keys, setKeys] = useState([])
  const [values, setValues] = useState({})
  const [reveal, setReveal] = useState({})
  const [saving, setSaving] = useState({})
  const [saved, setSaved] = useState({})

  useEffect(() => {
    fetch(`${API}/config/keys`)
      .then(r => r.json())
      .then(data => {
        setKeys(data)
        setValues(Object.fromEntries(data.map(k => [k.key, ''])))
      })
  }, [])

  async function save(key) {
    const val = values[key]
    if (!val.trim()) return
    setSaving(s => ({ ...s, [key]: true }))
    await fetch(`${API}/config/keys/${key}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: val }),
    })
    setSaving(s => ({ ...s, [key]: false }))
    setSaved(s => ({ ...s, [key]: true }))
    setValues(v => ({ ...v, [key]: '' }))
    fetch(`${API}/config/keys`).then(r => r.json()).then(setKeys)
    setTimeout(() => setSaved(s => ({ ...s, [key]: false })), 2000)
  }

  return (
    <div className="max-w-xl space-y-6">
      <h1 className="text-lg font-semibold">Settings</h1>

      <section className="space-y-4">
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">API Keys</h2>
        {keys.map(k => (
          <div key={k.key} className="bg-gray-800 rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{k.label}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${k.set ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-400'}`}>
                {k.set ? k.masked : 'not set'}
              </span>
            </div>
            <div className="flex gap-2">
              <input
                type={reveal[k.key] ? 'text' : 'password'}
                placeholder={k.set ? 'Enter new value to replace' : 'Paste key…'}
                value={values[k.key] ?? ''}
                onChange={e => setValues(v => ({ ...v, [k.key]: e.target.value }))}
                onKeyDown={e => e.key === 'Enter' && save(k.key)}
                className="flex-1 bg-gray-700 text-sm rounded px-3 py-2 outline-none focus:ring-1 focus:ring-blue-500 placeholder-gray-500"
              />
              <button
                onClick={() => setReveal(r => ({ ...r, [k.key]: !r[k.key] }))}
                className="px-2 py-2 text-gray-400 hover:text-white text-xs"
                title="Toggle visibility"
              >
                {reveal[k.key] ? 'Hide' : 'Show'}
              </button>
              <button
                onClick={() => save(k.key)}
                disabled={!values[k.key]?.trim() || saving[k.key]}
                className="px-4 py-2 text-sm rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {saved[k.key] ? 'Saved' : saving[k.key] ? '...' : 'Save'}
              </button>
            </div>
          </div>
        ))}
      </section>
    </div>
  )
}
