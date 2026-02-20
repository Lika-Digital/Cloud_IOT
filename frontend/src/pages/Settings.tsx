import ConfigPanel from '../components/config/ConfigPanel'

export default function Settings() {
  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-6">Settings</h1>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ConfigPanel />
        <div className="space-y-4">
          <div className="card">
            <h3 className="font-semibold text-white mb-3">Quick Start</h3>
            <ol className="text-sm text-gray-400 space-y-2 list-decimal list-inside">
              <li>Start the MQTT broker: <code className="text-blue-400">docker compose up -d</code></li>
              <li>Start the backend: <code className="text-blue-400">uvicorn app.main:app --reload</code></li>
              <li>Select <strong className="text-white">Synthetic Data</strong> mode and click Apply</li>
              <li>Go to Dashboard — socket events will appear within seconds</li>
              <li>Click Allow on pending sessions to activate them</li>
              <li>Click Stop to end sessions and archive them</li>
            </ol>
          </div>
          <div className="card">
            <h3 className="font-semibold text-white mb-3">MQTT Topics</h3>
            <div className="space-y-1 text-xs font-mono text-gray-400">
              <p className="text-gray-500">// Pedestal → Backend</p>
              <p>pedestal/{'{id}'}/socket/{'{1-4}'}/status</p>
              <p>pedestal/{'{id}'}/socket/{'{1-4}'}/power</p>
              <p>pedestal/{'{id}'}/water/flow</p>
              <p>pedestal/{'{id}'}/heartbeat</p>
              <p className="text-gray-500 mt-2">// Backend → Pedestal</p>
              <p>pedestal/{'{id}'}/socket/{'{1-4}'}/control</p>
              <p>pedestal/{'{id}'}/water/control</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
