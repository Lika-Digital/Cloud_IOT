import { useState, useEffect } from 'react'
import { useStore } from '../../store'
import { useAuthStore } from '../../store/authStore'
import { allowSession, denySession, stopSession } from '../../api'
import pedestalImg from '../../assets/pedestal.jpg'
import CameraModal from './CameraModal'

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

  const { pedestals, temperatureData, moistureData } = useStore()
  const pedestal = pedestals.find((p) => p.id === pedestalId)

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
            <AllSessionsOverview pedestalId={pedestalId} />
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
  const { pendingSessions, activeSessions } = useStore()

  const socketId = typeof zone.id === 'number' ? zone.id : null
  const isWater = zone.type === 'water'
  const isCamera = zone.type === 'camera'

  const pending = isCamera || isWater
    ? (!isCamera ? pendingSessions.find((s) => s.pedestal_id === pedestalId && s.type === 'water') : undefined)
    : pendingSessions.find((s) => s.pedestal_id === pedestalId && s.socket_id === socketId && s.type === 'electricity')

  const active = isCamera || isWater
    ? (!isCamera ? activeSessions.find((s) => s.pedestal_id === pedestalId && s.type === 'water') : undefined)
    : activeSessions.find((s) => s.pedestal_id === pedestalId && s.socket_id === socketId && s.type === 'electricity')

  const status = active ? 'active' : pending ? 'pending' : 'idle'

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

  return (
    <button
      style={posStyle}
      onClick={onClick}
      title={zone.label}
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
  )
}

// ─── Socket Detail Panel ─────────────────────────────────────────────────────

function SocketDetailPanel({ zoneId, pedestalId, onClose }: { zoneId: ZoneId; pedestalId: number; onClose: () => void }) {
  const { pendingSessions, activeSessions, socketLiveData, waterLiveData, updateSession } = useStore()
  const { role } = useAuthStore()
  const isAdmin = role === 'admin'

  const isWater = zoneId === 'water-left' || zoneId === 'water-right'
  const isCamera = zoneId === 'camera'
  const socketId = typeof zoneId === 'number' ? zoneId : null

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

  const handleAllow = async () => {
    if (!pendingSession) return
    const updated = await allowSession(pendingSession.id)
    updateSession({ id: updated.id, status: 'active' })
  }

  const handleDeny = async () => {
    if (!pendingSession) return
    const updated = await denySession(pendingSession.id)
    updateSession({ id: updated.id, status: 'denied' })
  }

  const handleStop = async () => {
    if (!activeSession) return
    const updated = await stopSession(activeSession.id)
    updateSession({ id: updated.id, status: 'completed' })
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
            {activeSession ? 'Active' : pendingSession ? 'Pending Approval' : 'Idle'}
          </span>
        </div>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-xl leading-none">✕</button>
      </div>

      {/* Pending state */}
      {pendingSession && !activeSession && (
        <div className="bg-amber-900/20 border border-amber-700/40 rounded-lg p-4 space-y-3">
          <p className="text-amber-300 font-medium">
            {isWater ? 'Water flow detected' : 'Device plugged in'} — awaiting approval
          </p>
          <p className="text-xs text-gray-400">
            Started: {new Date(pendingSession.started_at).toLocaleTimeString()}
          </p>
          {isAdmin ? (
            <div className="flex gap-3">
              <button className="btn-success flex-1" onClick={handleAllow}>Allow</button>
              <button className="btn-danger flex-1" onClick={handleDeny}>Deny</button>
            </div>
          ) : (
            <p className="text-xs text-gray-500 italic">Monitor role — contact an admin to approve</p>
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
      {!pendingSession && !activeSession && (
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
  const { pendingSessions, activeSessions } = useStore()
  const pending = pendingSessions.filter((s) => s.pedestal_id === pedestalId)
  const active  = activeSessions.filter((s) => s.pedestal_id === pedestalId)
  const total   = pending.length + active.length

  return (
    <div className="space-y-4">
      <div className="card">
        <h3 className="font-semibold text-gray-300 mb-3">Quick Status</h3>
        {total === 0 ? (
          <p className="text-gray-500 text-sm">All sockets idle. Click a socket on the pedestal to manage it.</p>
        ) : (
          <div className="space-y-2">
            {pending.map((s) => (
              <div key={s.id} className="flex items-center gap-2 text-sm">
                <span className="badge-pending">Pending</span>
                <span className="text-gray-300">
                  {s.type === 'water' ? 'Water' : `Socket ${s.socket_id}`}
                </span>
              </div>
            ))}
            {active.map((s) => (
              <div key={s.id} className="flex items-center gap-2 text-sm">
                <span className="badge-active">Active</span>
                <span className="text-gray-300">
                  {s.type === 'water' ? 'Water' : `Socket ${s.socket_id}`}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="card text-sm text-gray-500 space-y-1">
        <p className="font-medium text-gray-400 mb-2">Legend</p>
        <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-green-400 inline-block" /> Active session</div>
        <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-full bg-amber-400 animate-pulse inline-block" /> Pending approval</div>
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
