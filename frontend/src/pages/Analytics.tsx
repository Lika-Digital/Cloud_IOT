import { useEffect, useState } from 'react'
import { getDailyConsumption, getSessionSummary, getConsumptionBySocket } from '../api'
import type { DailyConsumption, SessionSummary } from '../api'
import ConsumptionChart from '../components/analytics/ConsumptionChart'
import PredictionPanel from '../components/analytics/PredictionPanel'

export default function Analytics() {
  const [dailyData, setDailyData] = useState<DailyConsumption[]>([])
  const [summary, setSummary] = useState<SessionSummary | null>(null)
  const [socketData, setSocketData] = useState<unknown[]>([])
  const [days, setDays] = useState(30)

  useEffect(() => {
    getDailyConsumption({ days }).then(setDailyData)
    getSessionSummary().then(setSummary)
    getConsumptionBySocket().then(setSocketData)
  }, [days])

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-6">Analytics</h1>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <SummaryCard label="Total Sessions" value={summary.total_sessions} />
          <SummaryCard label="Completed" value={summary.completed_sessions} />
          <SummaryCard
            label="Total Energy"
            value={`${summary.total_energy_kwh.toFixed(2)} kWh`}
          />
          <SummaryCard
            label="Total Water"
            value={`${summary.total_water_liters.toFixed(0)} L`}
          />
        </div>
      )}

      {/* Consumption chart */}
      <div className="card mb-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-white">Daily Consumption</h3>
          <select
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-white"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </div>
        <ConsumptionChart data={dailyData} />
      </div>

      {/* Socket breakdown */}
      {(socketData as { socket_id: number | null; type: string; total_energy_kwh: number; session_count: number }[]).length > 0 && (
        <div className="card mb-6">
          <h3 className="text-lg font-semibold text-white mb-4">Consumption by Socket</h3>
          <div className="space-y-2">
            {(socketData as { socket_id: number | null; type: string; total_energy_kwh: number; session_count: number }[]).map((row, i) => (
              <div key={i} className="flex items-center justify-between py-2 border-b border-gray-800 last:border-0">
                <span className="text-gray-300">
                  {row.type === 'electricity' ? `Socket ${row.socket_id}` : 'Water Meter'}
                </span>
                <div className="flex gap-6 text-sm">
                  <span className="text-gray-400">{row.session_count} sessions</span>
                  <span className="text-white font-mono">
                    {row.total_energy_kwh.toFixed(3)} kWh
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Prediction panel */}
      <PredictionPanel />
    </div>
  )
}

function SummaryCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="card">
      <p className="text-xs text-gray-400 mb-1">{label}</p>
      <p className="text-2xl font-bold text-white">{value}</p>
    </div>
  )
}
