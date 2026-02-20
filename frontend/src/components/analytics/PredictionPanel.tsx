import { useState, useEffect } from 'react'
import { usePrediction } from '../../hooks/usePrediction'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from 'recharts'

export default function PredictionPanel() {
  const { loading, result, error, status, predict, train, checkStatus } = usePrediction()
  const [sessionType, setSessionType] = useState<'electricity' | 'water'>('electricity')
  const [duration, setDuration] = useState(30)

  useEffect(() => {
    checkStatus()
  }, [])

  // Generate forecast curve data (0 to 2x input duration)
  const forecastData =
    result
      ? Array.from({ length: 11 }, (_, i) => {
          const mins = (duration * 2 * i) / 10
          const consumption = (result.predicted_consumption / result.predicted_duration_minutes) * mins
          return {
            minutes: Math.round(mins),
            consumption: Math.max(0, parseFloat(consumption.toFixed(4))),
          }
        })
      : []

  return (
    <div className="card space-y-4">
      <h3 className="text-lg font-semibold text-white">ML Consumption Forecast</h3>

      {/* Model status */}
      {status && (
        <div className="flex gap-4 text-sm">
          <ModelBadge label="Electricity" ready={status.electricity_model_ready} />
          <ModelBadge label="Water" ready={status.water_model_ready} />
        </div>
      )}

      {/* Train button */}
      <button
        className="btn-ghost text-sm"
        onClick={() => train()}
        disabled={loading}
      >
        {loading ? 'Training…' : 'Retrain Models'}
      </button>

      {/* Inputs */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-gray-400 mb-1">Session type</label>
          <select
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
            value={sessionType}
            onChange={(e) => setSessionType(e.target.value as 'electricity' | 'water')}
          >
            <option value="electricity">Electricity</option>
            <option value="water">Water</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Duration (minutes)</label>
          <input
            type="number"
            min={1}
            max={480}
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
          />
        </div>
      </div>

      <button
        className="btn-primary text-sm"
        onClick={() => predict(sessionType, duration)}
        disabled={loading}
      >
        {loading ? 'Predicting…' : 'Predict Consumption'}
      </button>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {/* Result */}
      {result && (
        <div className="space-y-3">
          <div className="bg-blue-900/20 border border-blue-700/30 rounded-lg p-3">
            <p className="text-sm text-gray-400">
              Predicted consumption for {result.predicted_duration_minutes} min session
            </p>
            <p className="text-2xl font-bold text-white">
              {result.predicted_consumption.toFixed(4)}{' '}
              <span className="text-base font-normal text-gray-400">{result.unit}</span>
            </p>
          </div>

          {forecastData.length > 0 && (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={forecastData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="minutes" stroke="#9ca3af" tick={{ fontSize: 11 }} label={{ value: 'Minutes', position: 'insideBottom', offset: -2, fill: '#9ca3af', fontSize: 11 }} />
                <YAxis stroke="#9ca3af" tick={{ fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                />
                <ReferenceLine
                  x={duration}
                  stroke="#f59e0b"
                  strokeDasharray="4 4"
                  label={{ value: 'Now', fill: '#f59e0b', fontSize: 11 }}
                />
                <Line
                  type="monotone"
                  dataKey="consumption"
                  name={result.unit}
                  stroke="#3b82f6"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      )}
    </div>
  )
}

function ModelBadge({ label, ready }: { label: string; ready: boolean }) {
  return (
    <span className={`badge ${ready ? 'badge-active' : 'bg-gray-800 text-gray-500 border border-gray-700'}`}>
      {label}: {ready ? 'Ready' : 'Not trained'}
    </span>
  )
}
