import { useState, useEffect } from 'react'
import { useStore } from '../../store'
import { useAuthStore } from '../../store/authStore'
import { stopSession, approveSocket, rejectSocket } from '../../api'
import pedestalImg from '../../assets/pedestal.jpg'
import CameraModal from './CameraModal'
import PedestalControlCenter from './PedestalControlCenter'

// Zone definitions — positions as % of image dimensions
// Each zone is positioned over the actual socket/pipe on the image
const SOCKET_ZONES = [
  { id: 1,             label: 'Socket 1', type: 'electricity' as const, color: 'blue',  left: '3%',   top: '37%', size: 52 },
  { id: 2,             label: 'Socket 2', type: 'electricity' as const, color: 'red',   left: '3%',   top: '52%', size: 52 },
  { id: 3,             label: 'Socket 3', type: 'electricity' as const, color: 'blue',  right: '3%',  top: '37%', size: 52 },
  { id: 4,             label: 'Socket 4', type: 'electricity' as const, color: 'red',   right: '3%',  top: '52%', size: 52 },
  { id: 'water-left',  label: 'Water L',  type: 'water'       as const, color: 'gray',  left: '4%',   top: '87%', size: 40 },
  { id: 'water-right', label: 'Water R',  type: 'water'       as const, color: 'gray',  right: '4%',  top: '87%', size: 40 },
  { id: 'camera',      label: 'Camera',   type: 'camera'      as const, color: 'black', right: '3%',  top: '10%', size: 38 },
]

type ZoneId = number | 'water-left' | 'water-right' | 'camera'

interface PedestalViewProps {
  pedestalId: number
}

export default function PedestalView({ pedestalId }: PedestalViewProps) {
  const [selectedZone, setSelectedZone] = useState<ZoneId | null>(null)
  const [cameraOpen, setCameraOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<'overview' | 'control'>('overview')

  const { pedestals, temperatureData, moistureData, marinaDoorState } = useStore()
  const pedestal = pedestals.find((p) => p.id === pedestalId)
  const doorState = marinaDoorState[pedestalId]

  const temp = temperatureData[pedestalId]
  const moist = moistureData[pedestalId]

  const handleZoneClick = (zoneId: ZoneId) => {
    if (zoneId === 'camera') {
      setCameraOpen(true)
      return
    }
    setSelectedZone(selectedZone === zoneId ? null : zoneId)
  }

  return (
    <>
      {cameraOpen && pedestal && (
        <CameraModal
          pedestalId={pedestalId}
          dataMode={pedestal.data_mode}
          cameraIp={pedestal.camera_ip}
          onClose={() => setCameraOpen(false)}
        />
      )}

      <div className="flex gap-6 items-start">
        {/* Pedestal image with clickable zones */}
        <div className="flex-shrink-0">
          <div className="relative inline-block select-none" style={{ height: 520 }}>
            <img
              src={pedestalImg}
              alt="Pedestal"
              className="h-full w-auto object-contain rounded-xl shadow-2xl"
              draggable={false}
            />
            {/* Clickable overlay zones */}
            {SOCKET_ZONES.map((zone) => (
              <ZoneButton
                key={zone.id}
                zone={zone}
                pedestalId={pedestalId}
                isSelected={selectedZone === zone.id}
                onClick={() => handleZoneClick(zone.id as ZoneId)}
              />
            ))}
          </div>
          <p className="text-xs text-gray-500 text-center mt-2">
            Click sockets, water pipes, or camera to manage
          </p>

          {/* Marina door status */}
          {doorState && (
            <div className={`flex items-center justify-center gap-2 mt-2 px-3 py-1.5 rounded-lg text-xs border ${
              doorState === 'open'
                ? 'bg-red-900/30 border-red-700/50 text-red-300 animate-pulse'
                : 'bg-gray-800 border-gray-700 text-gray-400'
            }`}>
              <span>{doorState === 'open' ? '🔓' : '🔒'}</span>
              <span>Cabinet door: <strong>{doorState === 'open' ? 'OPEN' : 'Closed'}</strong></span>
            </div>
          )}

          {/* Sensor readings bar */}
          <div className="flex gap-3 mt-3 justify-center">
            <SensorBadge
              icon="🌡️"
              label="Temp"
              value={temp ? `${temp.value}°C` : '—'}
              alarm={temp?.alarm ?? false}
              alarmText=">50°C"
            />
            <SensorBadge
              icon="💧"
              label="Moisture"
              value={moist ? `${moist.value}%` : '—'}
              alarm={moist?.alarm ?? false}
              alarmText=">90%"
            />
          </div>
        </div>

        {/* Detail panel */}
        <div className="flex-1 min-w-0">
          {selectedZone !== null ? (
            <SocketDetailPanel zoneId={selectedZone} pedestalId={pedestalId} onClose={() => setSelectedZone(null)} />
          ) : (
            <div className="space-y-3">
              {/* Tabs */}
              <div className="flex gap-1 bg-gray-800/60 rounded-lg p-1 border border-gray-700/60">
                <button
                  onClick={() => setActiveTab('overview')}
                  className={`flex-1 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    activeTab === 'overview'
                      ? 'bg-gray-700 text-white shadow-sm'
                      : 'text-gray-400 hover:text-gray-200'
                  }`}
                >
                  Overview
                </button>
                <button
                  onClick={() => setActiveTab('control')}
                  className={`flex-1 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    activeTab === 'control'
                      ? 'bg-gray-700 text-white shadow-sm'
                      : 'text-gray-400 hover:text-gray-200'
                  }`}
                >
                  Control Center
                </button>
              </div>

              {activeTab === 'overview' ? (
                <AllSessionsOverview pedestalId={pedestalId} />
              ) : (
                <PedestalControlCenter pedestalId={pedestalId} />
              )}
            </div>
          )}
        </div>
      </div>
    </>
  )
}

// ─── Zone Button ────────────────────────────────────────────────────────────

function ZoneButton({
  zone,
  pedestalId,
  isSelected,
  onClick,
}: {
  zone: (typeof SOCKET_ZONES)[0]
  pedestalId: number
  isSelected: boolean
  onClick: () => void
}) {
  const { pendingSessions, activeSessions, pendingSockets } = useStore()

  const socketId = typeof zone.id === 'number' ? zone.id : null
  const isWater = zone.type === 'water'
  const isCamera = zone.type === 'camera'

  const pending = isCamera || isWater
    ? (!isCamera ? pendingSessions.find((s) => s.pedestal_id === pedestalId && s.type === 'water') : undefined)
    : pendingSessions.find((s) => s.pedestal_id === pedestalId && s.socket_id === socketId && s.type === 'electricity')

  const active = isCamera || isWater
    ? (!isCamera ? activeSessions.find((s) => s.pedestal_id === pedestalId && s.type === 'water') : undefined)
    : activeSessions.find((s) => s.pedestal_id === pedestalId && s.socket_id === socketId && s.type === 'electricity')

  // Socket-level pending: MQTT connected, no session yet, waiting for operator/mobile
  const socketPending = !isCamera && !isWater && socketId !== null
    ? !!pendingSockets[`${pedestalId}-${socketId}`]
    : false

  const status = active ? 'active' : (pending || socketPending) ? 'pending' : 'idle'

  const ringColor = isCamera
    ? 'ring-gray-500 shadow-transparent'
    : {
        active: 'ring-green-400 shadow-green-400/60',
        pending: 'ring-amber-400 shadow-amber-400/60',
        idle: 'ring-gray-600 shadow-transparent',
      }[status]

  const bgColor = isCamera
    ? 'bg-black/70'
    : {
        active: 'bg-green-500/30',
        pending: 'bg-amber-500/30',
        idle: 'bg-white/10',
      }[status]

  const posStyle: React.CSSProperties = {
    position: 'absolute',
    top: zone.top,
    width: zone.size,
    height: zone.size,
    transform: 'translate(-50%, -50%)',
    ...(('left' in zone) ? { left: zone.left } : { right: zone.right }),
  }

  // Adjust transform for right-anchored zones
  if ('right' in zone) {
    posStyle.transform = 'translate(50%, -50%)'
  }

  const tooltipText = isCamera
    ? 'Camera'
    : status === 'active'
      ? 'Stop Session'
      : zone.label

  return (
    <div style={posStyle} className="group">
      <button
        style={{ width: '100%', height: '100%' }}
        onClick={onClick}
        className={`
          rounded-full border-2 cursor-pointer transition-all duration-200
          ring-2 shadow-lg ${ringColor} ${bgColor}
          ${isSelected ? 'scale-110 ring-4' : 'hover:scale-105'}
          ${status === 'pending' && !isCamera ? 'animate-pulse' : ''}
        `}
      >
        {isCamera && (
          <span className="flex items-center justify-center w-full h-full text-white text-xs">📷</span>
        )}
        {!isCamera && <span className="sr-only">{zone.label}</span>}
      </button>
      {/* Custom tooltip */}
      <div className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 opacity-0 group-hover:opacity-100 transition-opacity duration-150 z-10">
        <div className={`whitespace-nowrap text-xs px-2 py-1 rounded-md shadow-lg ${
          status === 'active' && !isCamera
            ? 'bg-red-700 text-white'
            : 'bg-gray-800 text-gray-200 border border-gray-600'
        }`}>
          {tooltipText}
        </div>
        <div className="flex justify-center">
          <div className={`w-1.5 h-1.5 rotate-45 -mt-1 ${
            status === 'active' && !isCamera ? 'bg-red-700' : 'bg-gray-800 border-b border-r border-gray-600'
          }`} />
        </div>
      </div>
    </div>
  )
}

// ─── Socket Detail Panel ─────────────────────────────────────────────────────

function SocketDetailPanel({ zoneId, pedestalId, onClose }: { zoneId: ZoneId; pedestalId: number; onClose: () => void }) {
  const { pendingSessions, activeSessions, socketLiveData, waterLiveData, updateSession, pendingSockets, addSession, removePendingSocket } = useStore()
  const { role } = useAuthStore()
  const isAdmin = role === 'admin'
  const [actionError, setActionError] = useState<string | null>(null)
  const [denyReason, setDenyReason] = useState('')
  const [approvalLoading, setApprovalLoading] = useState<'approve' | 'reject' | null>(null)

  const isWater = zoneId === 'water-left' || zoneId === 'water-right'
  const isCamera = zoneId === 'camera'
  const socketId = typeof zoneId === 'number' ? zoneId : null
  const socketPending = !isWater && !isCamera && socketId !== null
    ? !!pendingSockets[`${pedestalId}-${socketId}`]
    : false

  // Camera zone is handled by modal; this panel shouldn't appear for it
  if (isCamera) return null
  const zone = SOCKET_ZONES.find((z) => z.id === zoneId)!

  const pendingSession = isWater
    ? pendingSessions.find((s) => s.pedestal_id === pedestalId && s.type === 'water')
    : pendingSessions.find((s) => s.pedestal_id === pedestalId && s.socket_id === socketId && s.type === 'electricity')

  const activeSession = isWater
    ? activeSessions.find((s) => s.pedestal_id === pedestalId && s.type === 'water')
    : activeSessions.find((s) => s.pedestal_id === pedestalId && s.socket_id === socketId && s.type === 'electricity')

  const liveData = !isWater && socketId ? socketLiveData[socketId] : null

  const handleStop = async () => {
    if (!activeSession) return
    setActionError(null)
    try {
      const updated = await stopSession(activeSession.id)
      updateSession({ id: updated.id, status: 'completed' })
    } catch {
      setActionError('Stop failed — check connection and try again.')
    }
  }

  const handleApprove = async () => {
    if (!socketId) return
    setApprovalLoading('approve')
    setActionError(null)
    try {
      const session = await approveSocket(pedestalId, socketId)
      addSession({ ...session, status: 'active' })
      removePendingSocket(pedestalId, socketId)
    } catch {
      setActionError('Approve failed — check connection and try again.')
    } finally {
      setApprovalLoading(null)
    }
  }

  const handleReject = async () => {
    if (!socketId) return
    setApprovalLoading('reject')
    setActionError(null)
    try {
      await rejectSocket(pedestalId, socketId, denyReason || undefined)
      removePendingSocket(pedestalId, socketId)
      setDenyReason('')
    } catch {
      setActionError('Reject failed — check connection and try again.')
    } finally {
      setApprovalLoading(null)
    }
  }

  return (
    <div className="card space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`w-4 h-4 rounded-full ${
            activeSession ? 'bg-green-400 animate-pulse' :
            pendingSession ? 'bg-amber-400 animate-pulse' : 'bg-gray-600'
          }`} />
          <h3 className="text-lg font-bold text-white">{zone.label}</h3>
          <span className={
            activeSession ? 'badge-active' :
            pendingSession ? 'badge-pending' :
            'badge bg-gray-800 text-gray-500'
          }>
            {activeSession ? 'Active' : pendingSession ? 'Starting…' : 'Idle'}
          </span>
        </div>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-xl leading-none">✕</button>
      </div>

      {/* Action error */}
      {actionError && (
        <div className="bg-red-900/30 border border-red-700/50 text-red-300 text-sm px-3 py-2 rounded-lg">
          {actionError}
        </div>
      )}

      {/* Socket-level pending: MQTT connected, waiting for operator/mobile approval */}
      {socketPending && !pendingSession && !activeSession && (
        <div className="bg-amber-900/20 border border-amber-700/40 rounded-lg p-4 space-y-3">
          <p className="text-amber-300 font-medium">Device Connected — Awaiting Approval</p>
          <p className="text-xs text-gray-400">A device was plugged in. Approve to start the session or reject to deny.</p>
          {isAdmin && (
            <>
              <input
                type="text"
                placeholder="Rejection reason (optional)"
                value={denyReason}
                onChange={(e) => setDenyReason(e.target.value)}
                className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500"
              />
              <div className="flex gap-2">
                <button
                  onClick={handleApprove}
                  disabled={approvalLoading !== null}
                  className="flex-1 py-2 px-4 rounded-lg text-sm font-medium bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white transition-colors"
                >
                  {approvalLoading === 'approve' ? 'Approving…' : 'Approve'}
                </button>
                <button
                  onClick={handleReject}
                  disabled={approvalLoading !== null}
                  className="flex-1 py-2 px-4 rounded-lg text-sm font-medium bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white transition-colors"
                >
                  {approvalLoading === 'reject' ? 'Rejecting…' : 'Reject'}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Pending state (transient — session is activating via DB pending) */}
      {pendingSession && !activeSession && (
        <div className="bg-amber-900/20 border border-amber-700/40 rounded-lg p-4 space-y-2">
          <p className="text-amber-300 font-medium">Session starting…</p>
          {pendingSession.customer_name && (
            <p className="text-sm text-blue-300 font-medium">Customer: {pendingSession.customer_name}</p>
          )}
        </div>
      )}

      {/* Active state */}
      {activeSession && (
        <div className="space-y-3">
          <div className="bg-green-900/20 border border-green-700/40 rounded-lg p-4 space-y-3">
            {!isWater && liveData && (
              <>
                <LiveMetric label="Power" value={`${liveData.watts.toFixed(0)} W`} big />
                <LiveMetric label="Total Energy" value={`${liveData.kwh_total.toFixed(4)} kWh`} />
              </>
            )}
            {isWater && waterLiveData && (
              <>
                <LiveMetric label="Flow Rate" value={`${waterLiveData.lpm.toFixed(1)} L/min`} big />
                <LiveMetric label="Total" value={`${waterLiveData.total_liters.toFixed(2)} L`} />
              </>
            )}
            <SessionTimer startedAt={activeSession.started_at} />
          </div>
          {isAdmin && (
            <button className="btn-warning w-full" onClick={handleStop}>Stop Session</button>
          )}
        </div>
      )}

      {/* Idle state */}
      {!socketPending && !pendingSession && !activeSession && (
        <div className="text-center py-8 text-gray-500">
          <p className="text-4xl mb-3">{isWater ? '💧' : '🔌'}</p>
          <p>{isWater ? 'No water flow detected' : 'No device connected'}</p>
          <p className="text-xs mt-1">Waiting for connection…</p>
        </div>
      )}
    </div>
  )
}

// ─── Overview (no zone selected) ─────────────────────────────────────────────

function AllSessionsOverview({ pedestalId }: { pedestalId: number }) {
  const { activeSessions } = useStore()
  const active = activeSessions.filter((s) => s.pedestal_id === pedestalId)

  return (
    <div className="space-y-4">
      <div className="card">
        <h3 className="font-semibold text-gray-300 mb-3">Quick Status</h3>
        {active.length === 0 ? (
          <p className="text-gray-500 text-sm">All sockets idle. Click a socket on the pedestal to manage it.</p>
        ) : (
          <div className="space-y-2">
            {active.map((s) => (
              <div key={s.id} className="flex items-center gap-2 text-sm">
                <span className="badge-active">Active</span>
                <span className="text-gray-300">
                  {s.type === 'water' ? 'Water' : `Socket ${s.socket_id}`}
                </span>
                {s.customer_name && (
                  <span className="text-xs text-blue-300">· {s.customer_name}</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="card text-sm text-gray-500 space-y-1">
        <p className="font-medium text-gray-400 mb-2">Legend</p>
        <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-green-400 inline-block" /> Active session</div>
        <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-gray-600 inline-block" /> Idle</div>
      </div>
    </div>
  )
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function LiveMetric({ label, value, big }: { label: string; value: string; big?: boolean }) {
  return (
    <div className="flex justify-between items-center">
      <span className="text-gray-400 text-sm">{label}</span>
      <span className={`font-mono font-bold ${big ? 'text-2xl text-white' : 'text-gray-200'}`}>{value}</span>
    </div>
  )
}

function SensorBadge({
  icon,
  label,
  value,
  alarm,
  alarmText,
}: {
  icon: string
  label: string
  value: string
  alarm: boolean
  alarmText: string
}) {
  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm border ${
      alarm
        ? 'bg-red-900/30 border-red-700/50 text-red-300'
        : 'bg-gray-800 border-gray-700 text-gray-300'
    }`}>
      <span>{icon}</span>
      <span className="text-gray-400 text-xs">{label}</span>
      <span className="font-mono font-bold">{value}</span>
      {alarm && (
        <span className="text-xs bg-red-600 text-white px-1.5 py-0.5 rounded-full animate-pulse">
          ALARM {alarmText}
        </span>
      )}
    </div>
  )
}

function SessionTimer({ startedAt }: { startedAt: string }) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const start = new Date(startedAt).getTime()
    const interval = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000)
    return () => clearInterval(interval)
  }, [startedAt])

  const h = Math.floor(elapsed / 3600)
  const m = Math.floor((elapsed % 3600) / 60)
  const s = elapsed % 60
  const fmt = (n: number) => String(n).padStart(2, '0')

  return (
    <div className="flex justify-between items-center">
      <span className="text-gray-400 text-sm">Duration</span>
      <span className="font-mono font-bold text-white">{fmt(h)}:{fmt(m)}:{fmt(s)}</span>
    </div>
  )
}
