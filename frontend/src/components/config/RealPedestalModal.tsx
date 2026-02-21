/**
 * RealPedestalModal — shown when the user switches to "Real Pedestal" mode.
 * Collects the pedestal IP, camera IP, and shows MQTT broker info.
 * Includes format examples for every field.
 */
interface RealPedestalModalProps {
  pedestalName: string
  initialPedestalIp: string
  initialCameraIp: string
  mqttBroker: string
  onSave: (pedestalIp: string, cameraIp: string) => void
  onCancel: () => void
}

export default function RealPedestalModal({
  pedestalName,
  initialPedestalIp,
  initialCameraIp,
  mqttBroker,
  onSave,
  onCancel,
}: RealPedestalModalProps) {
  const [pedestalIp, setPedestalIp] = useState(initialPedestalIp)
  const [cameraIp, setCameraIp]     = useState(initialCameraIp)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl w-full max-w-lg mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
          <div>
            <h2 className="text-lg font-bold text-white">Configure Real Pedestal</h2>
            <p className="text-sm text-gray-400 mt-0.5">{pedestalName}</p>
          </div>
          <button onClick={onCancel} className="text-gray-500 hover:text-gray-300 text-xl leading-none">✕</button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-5">

          {/* Info banner */}
          <div className="bg-blue-900/20 border border-blue-700/40 rounded-lg px-4 py-3 text-sm text-blue-300 space-y-1">
            <p className="font-medium">Before connecting:</p>
            <ul className="text-blue-400 text-xs space-y-0.5 list-disc list-inside ml-1">
              <li>Arduino Opta must be powered on and connected to your LAN</li>
              <li>Opta firmware must point to this machine's MQTT broker address</li>
              <li>Broker: <span className="font-mono text-white">{mqttBroker}</span></li>
            </ul>
          </div>

          {/* Pedestal IP */}
          <FieldGroup
            label="Pedestal IP Address"
            required
            format="IPv4 — four groups of numbers separated by dots"
            example="192.168.1.10"
            hint="The LAN IP of the Arduino Opta. Check the Opta's display or your router's DHCP table."
          >
            <input
              type="text"
              value={pedestalIp}
              onChange={(e) => setPedestalIp(e.target.value)}
              placeholder="192.168.1.10"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-blue-500 focus:outline-none"
            />
          </FieldGroup>

          {/* Camera IP */}
          <FieldGroup
            label="IP Camera Address"
            format="IPv4 or hostname, optionally with port"
            example="192.168.1.20 or 192.168.1.20:8080"
            hint="Leave blank to use the synthetic demo video instead."
          >
            <input
              type="text"
              value={cameraIp}
              onChange={(e) => setCameraIp(e.target.value)}
              placeholder="192.168.1.20  (optional)"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:border-blue-500 focus:outline-none"
            />
          </FieldGroup>

          {/* MQTT broker (read-only info) */}
          <FieldGroup
            label="MQTT Broker"
            format="hostname or IP address, followed by port"
            example="192.168.1.5:1883 or localhost:1883"
            hint="The broker this application is connected to. Configure the same address in the Opta firmware."
            readOnly
          >
            <div className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-400 font-mono">
              {mqttBroker}
            </div>
          </FieldGroup>
        </div>

        {/* Footer */}
        <div className="flex gap-3 px-6 py-4 border-t border-gray-800">
          <button
            onClick={onCancel}
            className="flex-1 px-4 py-2 rounded-lg border border-gray-700 text-gray-300 text-sm hover:bg-gray-800 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => onSave(pedestalIp.trim(), cameraIp.trim())}
            disabled={!pedestalIp.trim()}
            className="flex-1 px-4 py-2 rounded-lg bg-green-700 hover:bg-green-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
          >
            Save & Connect
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── FieldGroup helper ────────────────────────────────────────────────────────

import { useState } from 'react'

function FieldGroup({
  label,
  required,
  format,
  example,
  hint,
  readOnly,
  children,
}: {
  label: string
  required?: boolean
  format: string
  example: string
  hint?: string
  readOnly?: boolean
  children: React.ReactNode
}) {
  const [showHelp, setShowHelp] = useState(false)

  return (
    <div>
      <div className="flex items-center gap-2 mb-1">
        <label className="block text-sm text-gray-400">
          {label}
          {required && <span className="text-red-400 ml-1">*</span>}
        </label>
        {!readOnly && (
          <button
            type="button"
            onClick={() => setShowHelp(!showHelp)}
            className="text-gray-600 hover:text-blue-400 transition-colors text-xs"
            title="Show format help"
          >
            ⓘ
          </button>
        )}
      </div>

      {children}

      {/* Inline format example — always visible below input */}
      <div className="mt-1.5 flex items-start gap-1.5">
        <span className="text-gray-600 text-xs font-mono mt-0.5">→</span>
        <div>
          <span className="text-xs text-gray-600">Format: </span>
          <span className="text-xs text-gray-500 font-mono">{example}</span>
        </div>
      </div>

      {/* Expanded help panel */}
      {showHelp && (
        <div className="mt-2 bg-gray-800 border border-gray-700 rounded-lg p-3 text-xs space-y-1">
          <p className="text-gray-300 font-medium">{format}</p>
          {hint && <p className="text-gray-500">{hint}</p>}
        </div>
      )}
    </div>
  )
}
