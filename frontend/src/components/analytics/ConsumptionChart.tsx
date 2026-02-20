import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts'
import type { DailyConsumption } from '../../api'

interface ConsumptionChartProps {
  data: DailyConsumption[]
}

export default function ConsumptionChart({ data }: ConsumptionChartProps) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500">
        No data available yet
      </div>
    )
  }

  const formatted = data.map((d) => ({
    ...d,
    date: new Date(d.date).toLocaleDateString('en-GB', { month: 'short', day: 'numeric' }),
    energy_kwh: parseFloat(d.energy_kwh.toFixed(3)),
    water_liters: parseFloat(d.water_liters.toFixed(1)),
  }))

  return (
    <ResponsiveContainer width="100%" height={300}>
      <ComposedChart data={formatted} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
        <XAxis dataKey="date" stroke="#9ca3af" tick={{ fontSize: 12 }} />
        <YAxis yAxisId="left" stroke="#9ca3af" tick={{ fontSize: 12 }} />
        <YAxis yAxisId="right" orientation="right" stroke="#9ca3af" tick={{ fontSize: 12 }} />
        <Tooltip
          contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: 8 }}
          labelStyle={{ color: '#f3f4f6' }}
        />
        <Legend />
        <Bar yAxisId="left" dataKey="energy_kwh" name="Energy (kWh)" fill="#3b82f6" opacity={0.8} />
        <Line
          yAxisId="right"
          type="monotone"
          dataKey="water_liters"
          name="Water (L)"
          stroke="#06b6d4"
          strokeWidth={2}
          dot={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
