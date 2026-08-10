import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getConfig, setConfig, getMode, setMode, getUniverse, addToUniverse, removeFromUniverse, getVapidPublicKey, subscribeNotifications, unsubscribeNotifications } from '../api.js'

const SENSITIVE = new Set(['coinbase_api_private_key', 'reddit_client_secret'])

function ModeSection({ currentMode, onChanged }) {
  const [confirm, setConfirm] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const switchToLive = async () => {
    setSaving(true)
    setError('')
    try {
      await setMode('live', true)
      setConfirm(false)
      onChanged()
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to switch mode')
    } finally {
      setSaving(false)
    }
  }

  const switchToPaper = async () => {
    setSaving(true)
    setError('')
    try {
      await setMode('paper')
      onChanged()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <div className="text-xs text-gray-500 mb-3">Trading Mode</div>
      <div className="flex items-center gap-3 mb-3">
        <span className={`font-bold text-sm ${currentMode === 'live' ? 'text-blue-400' : 'text-amber-400'}`}>
          {currentMode?.toUpperCase() ?? '—'}
        </span>
      </div>

      {currentMode === 'paper' && !confirm && (
        <button
          onClick={() => setConfirm(true)}
          className="text-xs px-3 py-1 rounded bg-blue-900 text-blue-300 hover:bg-blue-800 transition-colors"
        >
          Switch to Live
        </button>
      )}

      {currentMode === 'live' && (
        <button
          onClick={switchToPaper}
          disabled={saving}
          className="text-xs px-3 py-1 rounded bg-amber-900 text-amber-300 hover:bg-amber-800 disabled:opacity-40 transition-colors"
        >
          {saving ? 'Switching...' : 'Switch to Paper'}
        </button>
      )}

      {confirm && (
        <div className="border border-red-800 rounded-lg p-3 bg-red-950/30">
          <div className="text-sm text-red-300 mb-2 font-medium">Switch to LIVE trading?</div>
          <div className="text-xs text-red-400 mb-3">
            Real money will be at risk. All risk rules remain in effect.
            Ensure all paper trading validation criteria are met.
          </div>
          <div className="flex gap-2">
            <button
              onClick={switchToLive}
              disabled={saving}
              className="text-xs px-3 py-1 rounded bg-red-800 text-red-200 hover:bg-red-700 disabled:opacity-40 transition-colors"
            >
              {saving ? 'Switching...' : 'Confirm Switch'}
            </button>
            <button
              onClick={() => setConfirm(false)}
              className="text-xs px-3 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}
    </div>
  )
}

function ConfigSection() {
  const [config, setConfigState] = useState([])
  const [editing, setEditing] = useState(null)
  const [editVal, setEditVal] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getConfig().then(r => setConfigState(r.data)).catch(() => {})
  }, [])

  const save = async (key) => {
    setSaving(true)
    try {
      await setConfig(key, editVal)
      setConfigState(c => c.map(r => r.key === key ? { ...r, value: editVal } : r))
      setEditing(null)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <div className="text-xs text-gray-500 mb-3">Configuration</div>
      <div className="space-y-1">
        {config.map(({ key, value, updated_at }) => (
          <div key={key} className="flex items-center gap-3 py-1">
            <span className="text-xs text-gray-500 w-48 truncate" title={key}>{key}</span>
            {editing === key ? (
              <div className="flex items-center gap-2 flex-1">
                <input
                  value={editVal}
                  onChange={e => setEditVal(e.target.value)}
                  className="flex-1 bg-gray-800 border border-gray-600 rounded px-2 py-0.5 text-xs text-white focus:outline-none focus:border-gray-400"
                  autoFocus
                  onKeyDown={e => e.key === 'Enter' && save(key)}
                />
                <button onClick={() => save(key)} disabled={saving} className="text-xs text-green-400 hover:text-green-300 disabled:opacity-40">
                  {saving ? '...' : 'Save'}
                </button>
                <button onClick={() => setEditing(null)} className="text-xs text-gray-500 hover:text-gray-300">
                  Cancel
                </button>
              </div>
            ) : (
              <>
                <span className="text-xs text-gray-300 flex-1 truncate">
                  {SENSITIVE.has(key) ? '•••••••' : (value || '—')}
                </span>
                <button
                  onClick={() => { setEditing(key); setEditVal(value || '') }}
                  className="text-xs text-gray-600 hover:text-gray-300 transition-colors"
                >
                  edit
                </button>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function UniverseSection() {
  const [pool, setPool] = useState('stocks')
  const [tickers, setTickers] = useState([])
  const [newTicker, setNewTicker] = useState('')
  const [loading, setLoading] = useState(false)
  const [removing, setRemoving] = useState(null)

  const load = () => {
    setLoading(true)
    getUniverse(pool).then(r => setTickers(r.data)).finally(() => setLoading(false))
  }

  useEffect(load, [pool])

  const add = async () => {
    const t = newTicker.trim().toUpperCase()
    if (!t) return
    await addToUniverse(pool, t)
    setNewTicker('')
    load()
  }

  const remove = async (ticker) => {
    setRemoving(ticker)
    try {
      await removeFromUniverse(pool, ticker)
      load()
    } finally {
      setRemoving(null)
    }
  }

  const active = tickers.filter(t => t.active !== 0)

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <div className="flex items-center gap-3 mb-3">
        <div className="text-xs text-gray-500">Universe</div>
        <div className="flex gap-1">
          {['stocks', 'crypto'].map(p => (
            <button
              key={p}
              onClick={() => setPool(p)}
              className={`px-2 py-0.5 text-xs rounded ${pool === p ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-white'}`}
            >
              {p}
            </button>
          ))}
        </div>
        <span className="text-xs text-gray-600 ml-auto">{active.length} active</span>
      </div>

      <div className="flex gap-2 mb-3">
        <input
          value={newTicker}
          onChange={e => setNewTicker(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && add()}
          placeholder="Add ticker"
          className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-gray-500 w-32"
        />
        <button
          onClick={add}
          disabled={!newTicker.trim()}
          className="text-xs px-2 py-1 bg-gray-700 text-white rounded disabled:opacity-40 hover:bg-gray-600 transition-colors"
        >
          Add
        </button>
      </div>

      {loading ? (
        <div className="text-gray-500 text-xs">Loading...</div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {active.map(t => (
            <div key={t.ticker} className="flex items-center gap-1 bg-gray-800 rounded px-2 py-1">
              <span className="text-xs text-white">{t.ticker}</span>
              <button
                onClick={() => remove(t.ticker)}
                disabled={removing === t.ticker}
                className="text-xs text-gray-600 hover:text-red-400 transition-colors ml-1 disabled:opacity-40"
              >
                ×
              </button>
            </div>
          ))}
          {active.length === 0 && <span className="text-xs text-gray-600">Empty</span>}
        </div>
      )}
    </div>
  )
}

function urlB64ToUint8Array(b64) {
  const pad = '='.repeat((4 - b64.length % 4) % 4)
  const raw = atob(b64.replace(/-/g, '+').replace(/_/g, '/') + pad)
  return Uint8Array.from(raw, c => c.charCodeAt(0))
}

const PUSH_SUPPORTED = typeof window !== 'undefined' &&
  'Notification' in window && 'serviceWorker' in navigator && 'PushManager' in window

function NotificationsSection() {
  const [perm, setPerm] = useState(PUSH_SUPPORTED ? Notification.permission : 'unsupported')
  const [subscribed, setSubscribed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!PUSH_SUPPORTED) return
    navigator.serviceWorker.getRegistration('/trading/').then(reg => {
      reg?.pushManager.getSubscription().then(sub => setSubscribed(!!sub))
    })
  }, [])

  const subscribe = async () => {
    setBusy(true)
    setError('')
    try {
      const permission = await Notification.requestPermission()
      setPerm(permission)
      if (permission !== 'granted') return

      const { data } = await getVapidPublicKey()
      const reg = await navigator.serviceWorker.register('/trading/sw.js', { scope: '/trading/' })
      await navigator.serviceWorker.ready
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlB64ToUint8Array(data.publicKey),
      })
      await subscribeNotifications(sub.toJSON())
      setSubscribed(true)
    } catch (e) {
      setError(e.message || 'Subscription failed')
    } finally {
      setBusy(false)
    }
  }

  const unsubscribe = async () => {
    setBusy(true)
    setError('')
    try {
      const reg = await navigator.serviceWorker.getRegistration('/trading/')
      const sub = await reg?.pushManager.getSubscription()
      if (sub) {
        await unsubscribeNotifications(sub.endpoint)
        await sub.unsubscribe()
      }
      setSubscribed(false)
    } catch (e) {
      setError(e.message || 'Failed to unsubscribe')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <div className="text-xs text-gray-500 mb-3">Push Notifications</div>

      {!PUSH_SUPPORTED && (
        <div className="text-xs text-gray-600">Not supported in this browser</div>
      )}

      {PUSH_SUPPORTED && perm === 'denied' && (
        <div className="text-xs text-red-400">Notifications blocked — enable in browser settings</div>
      )}

      {PUSH_SUPPORTED && perm !== 'denied' && (
        <div className="flex items-center gap-3">
          <span className={`w-2 h-2 rounded-full ${subscribed ? 'bg-green-500' : 'bg-gray-600'}`} />
          <span className="text-xs text-gray-400">{subscribed ? 'Enabled on this device' : 'Disabled'}</span>
          {subscribed ? (
            <button
              onClick={unsubscribe}
              disabled={busy}
              className="text-xs px-3 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600 disabled:opacity-40 transition-colors ml-auto"
            >
              {busy ? '...' : 'Disable'}
            </button>
          ) : (
            <button
              onClick={subscribe}
              disabled={busy}
              className="text-xs px-3 py-1 rounded bg-gray-700 text-white hover:bg-gray-600 disabled:opacity-40 transition-colors ml-auto"
            >
              {busy ? '...' : 'Enable'}
            </button>
          )}
        </div>
      )}

      {error && <div className="mt-2 text-xs text-red-400">{error}</div>}
      <div className="mt-2 text-xs text-gray-600">Alerts: morning brief, force exits</div>
    </div>
  )
}

export default function Settings() {
  const [mode, setCurrentMode] = useState(null)

  const loadMode = () => getMode().then(r => setCurrentMode(r.data.trading_mode)).catch(() => {})

  useEffect(() => { loadMode() }, [])

  return (
    <div className="p-6 pb-20 md:pb-6 max-w-2xl">
      <h1 className="text-lg font-bold text-white mb-6">Settings</h1>
      <ModeSection currentMode={mode} onChanged={loadMode} />
      <NotificationsSection />

      {/* Validation — desktop shows it in sidebar, mobile needs this link */}
      <div className="md:hidden bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
        <Link to="/validation" className="text-sm text-gray-300 hover:text-white transition-colors">
          Paper Trading Validation →
        </Link>
        <div className="text-xs text-gray-600 mt-1">Check readiness criteria before switching to live</div>
      </div>

      <ConfigSection />
      <UniverseSection />
    </div>
  )
}
