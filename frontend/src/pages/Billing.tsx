import { useState, useEffect } from 'react'
import {
  getBillingConfig, setBillingConfig, getSpendingOverview,
  type BillingConfig, type SpendingRow,
} from '../api/billing'

export default function Billing() {
  const [config, setConfig] = useState<BillingConfig | null>(null)
  const [kwh, setKwh] = useState('')
  const [liter, setLiter] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [spending, setSpending] = useState<SpendingRow[]>([])

  useEffect(() => {
    getBillingConfig().then((c) => {
      setConfig(c)
      setKwh(String(c.kwh_price_eur))
      setLiter(String(c.liter_price_eur))
    }).catch(() => {})
    getSpendingOverview().then(setSpending).catch(() => {})
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try {
      const updated = await setBillingConfig({
        kwh_price_eur: parseFloat(kwh),
        liter_price_eur: parseFloat(liter),
      })
      setConfig(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {
      // Error visible via toast/console; don't crash the form
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
    </div>
  )
}
