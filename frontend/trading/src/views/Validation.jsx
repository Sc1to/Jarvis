import { useEffect, useState } from 'react'
import { getValidationStatus, setConfig } from '../api.js'

function CriterionRow({ id, criterion, onConfirm }) {
  const [confirming, setConfirming] = useState(false)

  const confirm = async () => {
    setConfirming(true)
    try {
      await setConfig(id, 'true')
      onConfirm()
    } finally {
      setConfirming(false)
    }
  }

  return (
    <div className="flex items-start gap-3 py-3 border-t border-gray-800 first:border-t-0">
      <span className={`mt-0.5 w-4 h-4 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-bold ${
        criterion.pass ? 'bg-green-900 text-green-300' : 'bg-gray-800 text-gray-600'
      }`}>
        {criterion.pass ? '✓' : '·'}
      </span>
      <div className="flex-1 min-w-0">
        <div className={`text-sm ${criterion.pass ? 'text-white' : 'text-gray-400'}`}>
          {criterion.label}
        </div>
        <div className="text-xs text-gray-600 mt-0.5">{criterion.detail}</div>
      </div>
      {criterion.manual && !criterion.pass && (
        <button
          onClick={confirm}
          disabled={confirming}
          className="text-xs px-2 py-1 bg-gray-700 text-gray-300 rounded hover:bg-gray-600 disabled:opacity-40 flex-shrink-0 transition-colors"
        >
          {confirming ? '...' : 'Confirm'}
        </button>
      )}
      {!criterion.manual && (
        <span className="text-xs text-gray-600 flex-shrink-0 tabular-nums">
          target: {criterion.target}
        </span>
      )}
    </div>
  )
}

export default function Validation() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    getValidationStatus()
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const allPass = data?.all_pass
  const autoPass = data?.automatable_pass
  const passCount = data ? Object.values(data.criteria).filter(c => c.pass).length : 0
  const total = data ? Object.keys(data.criteria).length : 0

  return (
    <div className="p-6 pb-20 md:pb-6 max-w-2xl">
      <h1 className="text-lg font-bold text-white mb-2">Paper Trading Validation</h1>
      <p className="text-xs text-gray-500 mb-6">
        All criteria must pass before switching to live trading.
        Minimum 3 months of continuous paper operation required.
      </p>

      {loading && <div className="text-gray-500 text-sm">Loading...</div>}

      {!loading && !data && (
        <div className="text-red-400 text-sm">Could not load validation data — is the trading service running?</div>
      )}

      {data && (
        <>
          {/* Status banner */}
          <div className={`rounded-lg p-4 mb-6 border ${
            allPass
              ? 'bg-green-950 border-green-800'
              : 'bg-gray-900 border-gray-800'
          }`}>
            <div className={`text-sm font-bold mb-1 ${allPass ? 'text-green-300' : 'text-gray-300'}`}>
              {allPass ? 'Ready for live switch review' : `${passCount} / ${total} criteria met`}
            </div>
            <div className="text-xs text-gray-500">
              {allPass
                ? 'All criteria pass. Schedule a review conversation before switching to live.'
                : autoPass
                  ? 'Automatable checks pass — manual confirmations remaining.'
                  : `${data.days_since_start} day${data.days_since_start !== 1 ? 's' : ''} of paper trading so far.`
              }
            </div>
          </div>

          {/* Automated criteria */}
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-4">
            <div className="text-xs text-gray-500 mb-3">Automated checks</div>
            {Object.entries(data.criteria)
              .filter(([, v]) => !v.manual)
              .map(([id, criterion]) => (
                <CriterionRow key={id} id={id} criterion={criterion} onConfirm={load} />
              ))}
          </div>

          {/* Manual criteria */}
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
            <div className="text-xs text-gray-500 mb-3">Manual confirmations</div>
            {Object.entries(data.criteria)
              .filter(([, v]) => v.manual)
              .map(([id, criterion]) => (
                <CriterionRow key={id} id={id} criterion={criterion} onConfirm={load} />
              ))}
          </div>

          <div className="mt-4 text-xs text-gray-600">
            The live switch is a conversation, not just a button press. Review all results
            with the user before activating.
          </div>
        </>
      )}
    </div>
  )
}
