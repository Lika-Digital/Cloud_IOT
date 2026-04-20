import { useEffect, useState } from 'react'
import { getDailyConsumption, getSessionSummary, getConsumptionBySocket, getConsumptionByPedestal, getPedestals } from '../api'
import type { DailyConsumption, SessionSummary, PedestalConsumption } from '../api'
import type { Pedestal } from '../store'
import ConsumptionChart from '../components/analytics/ConsumptionChart'
import PredictionPanel from '../components/analytics/PredictionPanel'
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend,
} from 'recharts'

interface SocketBreakdownRow {
  socket_id: number | null
  type: string
  total_energy_kwh: number
  total_water_liters?: number
  session_count: number
}

export default function Analytics() {
  const [pedestals, setPedestals]       = useState<Pedestal[]>([])
  const [selectedId, setSelectedId]     = useState<number | undefined>(undefined)
  const [dailyData, setDailyData]       = useState<DailyConsumption[]>([])
  const [summary, setSummary]           = useState<SessionSummary | null>(null)
  const [socketData, setSocketData]     = useState<SocketBreakdownRow[]>([])
  const [comparison, setComparison]     = useState<PedestalConsumption[]>([])
  const [days, setDays]                 = useState(30)

  useEffect(() => {
    getPedestals().then(setPedestals)
    getConsumptionByPedestal().then(setComparison)
  }, [])

  useEffect(() => {
    getDailyConsumption({ pedestal_id: selectedId, days }).then(setDailyData)
    getSessionSummary(selectedId).then(setSummary)
    getConsumptionBySocket(selectedId).then(setSocketData)
  }, [selectedId, days])

  // Build comparison chart data labelled by pedestal name
  const comparisonData = comparison.map((row) => {
    const p = pedestals.find((x) => x.id === row.pedestal_id)
    return {
      name: p?.name ?? `Pedestal ${row.pedestal_id}`,
      energy_kwh: row.total_energy_kwh,
      water_liters: row.total_water_liters,
      sessions: row.session_count,
    }
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Analytics</h1>

        {/* Pedestal filter */}
        <select
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-white"
          value={selectedId ?? ''}
          onChange={(e) => setSelectedId(e.target.value ? Number(e.target.value) : undefined)}
        >
          <option value="">All Pedestals</option>
          {pedestals.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <SummaryCard label="Total Sessions"  value={summary.total_sessions} />
          <SummaryCard label="Completed"        value={summary.completed_sessions} />
          <SummaryCard label="Total Energy"     value={`${summary.total_energy_kwh.toFixed(2)} kWh`} />
          <SummaryCard label="Total Water"      value={`${summary.total_water_liters.toFixed(0)} L`} />
        </div>
      )}

      {/* Cross-pedestal comparison (only when showing all) */}
      {!selectedId && comparisonData.length > 1 && (
        <div className="card mb-6">
          <h3 className="text-lg font-semibold text-white mb-4">Pedestal Comparison</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={comparisonData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="name" stroke="#9ca3af" tick={{ fontSize: 12 }} />
              <YAxis yAxisId="left"  stroke="#9ca3af" tick={{ fontSize: 12 }} />
              <YAxis yAxisId="right" orientation="right" stroke="#9ca3af" tick={{ fontSize: 12 }} />
              <Tooltip
                contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                labelStyle={{ color: '#f3f4f6' }}
              />
              <Legend />
              <Bar yAxisId="left"  dataKey="energy_kwh"   name="Energy (kWh)" fill="#3b82f6" />
              <Bar yAxisId="right" dataKey="water_liters"  name="Water (L)"    fill="#06b6d4" />
            </BarChart>
          </ResponsiveContainer>

          {/* Comparison table */}
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-gray-400">
                  <th className="py-2 px-3">Pedestal</th>
                  <th className="py-2 px-3">Sessions</th>
                  <th className="py-2 px-3">Energy (kWh)</th>
                  <th className="py-2 px-3">Water (L)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {comparisonData.map((row, i) => (
                  <tr key={i} className="hover:bg-gray-800/50">
                    <td className="py-2 px-3 text-white font-medium">{row.name}</td>
                    <td className="py-2 px-3 text-gray-300">{row.sessions}</td>
                    <td className="py-2 px-3 font-mono text-gray-200">{row.energy_kwh.toFixed(3)}</td>
                    <td className="py-2 px-3 font-mono text-gray-200">{row.water_liters.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Daily consumption chart */}
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

      {/* Socket breakdown — electricity sockets + water meters */}
      {(socketData as SocketBreakdownRow[]).length > 0 && (
        <div className="card mb-6">
          <h3 className="text-lg font-semibold text-white mb-4">Consumption by Socket</h3>
          <div className="space-y-2">
            {(socketData as SocketBreakdownRow[])
              .slice()
              .sort((a, b) => {
                if (a.type !== b.type) return a.type === 'electricity' ? -1 : 1
                return (a.socket_id ?? 0) - (b.socket_id ?? 0)
              })
              .map((row, i) => {
                const isWater = row.type === 'water'
                const label = isWater
                  ? `Water Meter${row.socket_id ? ` ${row.socket_id}` : ''}`
                  : `Socket ${row.socket_id}`
                const value = isWater
                  ? `${(row.total_water_liters ?? 0).toFixed(1)} L`
                  : `${(row.total_energy_kwh ?? 0).toFixed(3)} kWh`
                return (
                  <div key={i} className="flex items-center justify-between py-2 border-b border-gray-800 last:border-0">
                    <span className="text-gray-300 flex items-center gap-2">
                      <span className={isWater ? 'text-cyan-400' : 'text-blue-400'}>
                        {isWater ? '💧' : '⚡'}
                      </span>
                      {label}
                    </span>
                    <div className="flex gap-6 text-sm">
                      <span className="text-gray-400">{row.session_count} sessions</span>
                      <span className="text-white font-mono">{value}</span>
                    </div>
                  </div>
                )
              })}
          </div>
        </div>
      )}

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
