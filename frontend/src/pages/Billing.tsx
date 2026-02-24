import { useState, useEffect } from 'react'
import {
  getBillingConfig, setBillingConfig, getSpendingOverview, getSpendingDetail,
  type BillingConfig, type SpendingRow, type SessionDetailRow,
} from '../api/billing'

export default function Billing() {
  const [config, setConfig] = useState<BillingConfig | null>(null)
  const [kwh, setKwh] = useState('')
  const [liter, setLiter] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [spending, setSpending] = useState<SpendingRow[]>([])
  const [detail, setDetail] = useState<SessionDetailRow[]>([])
  const [expandedCustomer, setExpandedCustomer] = useState<number | null>(null)

  useEffect(() => {
    Promise.all([
      getBillingConfig().then((c) => {
        setConfig(c)
        setKwh(String(c.kwh_price_eur))
        setLiter(String(c.liter_price_eur))
      }),
      getSpendingOverview().then(setSpending),
      getSpendingDetail().then(setDetail),
    ]).catch(() => setLoadError('Failed to load billing data. Check your connection and refresh.'))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await setBillingConfig({
        kwh_price_eur: parseFloat(kwh),
        liter_price_eur: parseFloat(liter),
      })
      setConfig(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {
      setSaveError('Failed to save price configuration. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Billing</h1>
        <p className="text-gray-400 text-sm mt-1">Configure prices and view customer spending</p>
      </div>

      {loadError && (
        <div className="px-4 py-3 rounded-lg bg-red-900/30 border border-red-700/40 text-red-400 text-sm">
          {loadError}
        </div>
      )}

      {/* Price config */}
      <div className="card max-w-md space-y-4">
        <h2 className="font-semibold text-gray-200">Price Configuration</h2>
        <div>
          <label className="text-xs text-gray-400 block mb-1">Electricity price (€/kWh)</label>
          <input
            type="number"
            step="0.01"
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 text-sm focus:outline-none focus:border-blue-500"
            value={kwh}
            onChange={(e) => setKwh(e.target.value)}
          />
        </div>
        <div>
          <label className="text-xs text-gray-400 block mb-1">Water price (€/liter)</label>
          <input
            type="number"
            step="0.001"
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 text-sm focus:outline-none focus:border-blue-500"
            value={liter}
            onChange={(e) => setLiter(e.target.value)}
          />
        </div>
        <button
          className="w-full py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          onClick={handleSave}
          disabled={saving}
        >
          {saved ? 'Saved!' : saving ? 'Saving…' : 'Save Prices'}
        </button>
        {saveError && (
          <p className="text-sm text-red-400 bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">{saveError}</p>
        )}
        {config && (
          <p className="text-xs text-gray-500">Last updated: {new Date(config.updated_at).toLocaleString()}</p>
        )}
      </div>

      {/* Spending table */}
      <div className="card">
        <h2 className="font-semibold text-gray-200 mb-4">Customer Spending Overview</h2>
        {spending.length === 0 ? (
          <p className="text-gray-500 text-sm">No invoices yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700 text-gray-400 text-left">
                  <th className="py-2 pr-4">Customer</th>
                  <th className="py-2 pr-4">Sessions</th>
                  <th className="py-2 pr-4">Energy (kWh)</th>
                  <th className="py-2 pr-4">Water (L)</th>
                  <th className="py-2">Total (€)</th>
                </tr>
              </thead>
              <tbody>
                {spending.map((row) => (
                  <tr key={row.customer_id} className="border-b border-gray-800 hover:bg-gray-800/50">
                    <td className="py-2 pr-4">
                      <div className="text-gray-200">{row.customer_name ?? '—'}</div>
                      <div className="text-xs text-gray-500">{row.customer_email}</div>
                    </td>
                    <td className="py-2 pr-4 text-gray-300">{row.session_count}</td>
                    <td className="py-2 pr-4 text-gray-300 font-mono">{row.total_kwh.toFixed(4)}</td>
                    <td className="py-2 pr-4 text-gray-300 font-mono">{row.total_liters.toFixed(2)}</td>
                    <td className="py-2 text-green-400 font-mono font-bold">€{row.total_eur.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Session breakdown accordion */}
      <div className="card">
        <h2 className="font-semibold text-gray-200 mb-4">Session Breakdown</h2>
        {detail.length === 0 ? (
          <p className="text-gray-500 text-sm">No session data yet.</p>
        ) : (
          <div className="space-y-2">
            {spending.map((customer) => {
              const sessions = detail.filter((d) => d.customer_id === customer.customer_id)
              const isOpen = expandedCustomer === customer.customer_id
              return (
                <div key={customer.customer_id} className="border border-gray-700 rounded-lg overflow-hidden">
                  <button
                    className="w-full flex items-center justify-between px-4 py-3 text-sm text-gray-200 hover:bg-gray-800/50 transition-colors"
                    onClick={() => setExpandedCustomer(isOpen ? null : customer.customer_id)}
                  >
                    <span className="font-medium">{customer.customer_name ?? customer.customer_email}</span>
                    <span className="text-gray-400">{sessions.length} sessions {isOpen ? '▲' : '▼'}</span>
                  </button>
                  {isOpen && (
                    <div className="overflow-x-auto border-t border-gray-700">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="bg-gray-800/50 text-gray-400 text-left">
                            <th className="py-2 px-3">Date</th>
                            <th className="py-2 px-3">Type</th>
                            <th className="py-2 px-3">Energy</th>
                            <th className="py-2 px-3">Water</th>
                            <th className="py-2 px-3">Cost</th>
                            <th className="py-2 px-3">Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {sessions.map((s) => (
                            <tr key={s.session_id} className="border-t border-gray-800 hover:bg-gray-800/30">
                              <td className="py-2 px-3 text-gray-300 font-mono">
                                {s.started_at ? new Date(s.started_at).toLocaleDateString() : '—'}
                              </td>
                              <td className="py-2 px-3 text-gray-300 capitalize">{s.session_type}</td>
                              <td className="py-2 px-3 text-gray-300 font-mono">
                                {s.energy_kwh != null ? `${s.energy_kwh.toFixed(3)} kWh` : '—'}
                              </td>
                              <td className="py-2 px-3 text-gray-300 font-mono">
                                {s.water_liters != null ? `${s.water_liters.toFixed(1)} L` : '—'}
                              </td>
                              <td className="py-2 px-3 text-green-400 font-mono font-bold">€{s.total_eur.toFixed(2)}</td>
                              <td className="py-2 px-3">
                                <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                                  s.paid ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'
                                }`}>
                                  {s.paid ? 'Paid' : 'Unpaid'}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
