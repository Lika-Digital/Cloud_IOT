import { useState, useEffect } from 'react'
import { useStore } from '../../store'
import { useAuthStore } from '../../store/authStore'
import { getSocketBreakerStatus } from '../../api/breakers'
import pedestalImg from '../../assets/pedestal.jpg'
import CameraModal from './CameraModal'
import PedestalControlCenter from './PedestalControlCenter'
import SocketUsageHistoryModal from './SocketUsageHistoryModal'

// Zone definitions — positions as % of image dimensions
// Each zone is positioned over the actual socket/pipe on the image
const SOCKET_ZONES = [
  { id: 1,             label: 'Socket 1', type: 'electricity' as const, color: 'blue',  left: '3%',   top: '37%', size: 52 },
  { id: 2,             label: 'Socket 2', type: 'electricity' as const, color: 'red',   left: '3%',   top: '52%', size: 52 },
  { id: 3,             label: 'Socket 3', type: 'electricity' as const, color: 'blue',  right: '3%',  top: '37%', size: 52 },
  { id: 4,             label: 'Socket 4', type: 'electricity' as const, color: 'red',   right: '3%',  top: '52%', size: 52 },
  { id: 'water-left',  label: 'Water V1', type: 'water'       as const, color: 'gray',  left: '4%',   top: '87%', size: 40, valve: 'V1' as const },
  { id: 'water-right', label: 'Water V2', type: 'water'       as const, color: 'gray',  right: '4%',  top: '87%', size: 40, valve: 'V2' as const },
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
  const setBreakerState = useStore((s) => s.setBreakerState)
  const pedestal = pedestals.find((p) => p.id === pedestalId)
  const doorState = marinaDoorState[pedestalId]

  // v3.32 — hydrate breaker state on load. `breaker_state_changed` is a
  // change-only WS event published once (often when the backend processes the
  // retained breaker message at startup), so a browser that connects later
  // never receives it and the panel shows "Unknown / Not reported". Fetch the
  // current state for every socket from the DB so the badge, the click-panel,
  // and the Control Center all reflect reality (incl. a tripped breaker as the
  // fault reason) regardless of when the page loaded — in BOTH smart modes.
  useEffect(() => {
    let cancelled = false
    for (const sid of [1, 2, 3, 4]) {
      getSocketBreakerStatus(pedestalId, sid)
        .then((r) => {
          if (cancelled) return
          setBreakerState(pedestalId, sid, {
            breaker_state: r.breaker_state,
            trip_cause: r.breaker_trip_cause,
            breaker_type: r.breaker_type,
            breaker_rating: r.breaker_rating,
            breaker_poles: r.breaker_poles,
            breaker_rcd: r.breaker_rcd,
            breaker_rcd_sensitivity: r.breaker_rcd_sensitivity,
            last_trip_at: r.breaker_last_trip_at,
            trip_count: r.breaker_trip_count,
          })
        })
        .catch(() => { /* leave as 'unknown' — socket may have no breaker yet */ })
    }
    return () => { cancelled = true }
  }, [pedestalId, setBreakerState])

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
  const { pendingSessions, activeSessions, pendingSockets, optaWaterStates, socketComputedStates, socketAutoActivate, socketBreakerStates } = useStore()

  const socketId = typeof zone.id === 'number' ? zone.id : null
  const isWater = zone.type === 'water'
  const isCamera = zone.type === 'camera'
  const valveName = isWater && 'valve' in zone ? zone.valve : null

  // Per-valve firmware state (V1 / V2 tracked independently via opta/water/V*/status)
  const valveState = valveName ? optaWaterStates[`${pedestalId}-${valveName}`] : null

  // Unified state broadcast from backend for electricity sockets. Takes priority
  // over session-based inference when present — reflects plug-in status even
  // before a session exists.
  const computed = !isCamera && !isWater && socketId !== null
    ? socketComputedStates[`${pedestalId}-${socketId}`]
    : undefined

  const pending = isCamera
    ? undefined
    : isWater
      ? undefined
      : pendingSessions.find((s) => s.pedestal_id === pedestalId && s.socket_id === socketId && s.type === 'electricity')

  const active = isCamera
    ? undefined
    : isWater
      ? (valveState?.state === 'active' ? valveState : undefined)
      : activeSessions.find((s) => s.pedestal_id === pedestalId && s.socket_id === socketId && s.type === 'electricity')

  // Socket-level pending: MQTT connected, no session yet, waiting for operator/mobile
  const socketPending = !isCamera && !isWater && socketId !== null
    ? !!pendingSockets[`${pedestalId}-${socketId}`]
    : false

  // Status resolution: computed state from backend wins when we have it;
  // otherwise fall back to session / socket-pending inference.
  let status: 'idle' | 'pending' | 'active'
  if (computed) {
    status = computed === 'fault' ? 'idle' : computed
  } else {
    status = active ? 'active' : (pending || socketPending) ? 'pending' : 'idle'
  }

  const ringColor = isCamera
    ? 'ring-gray-500 shadow-transparent'
    : {
        active: 'ring-green-400 shadow-green-400/60',
        // Yellow for "plug inserted, awaiting activation" — matches Control Center badge.
        pending: 'ring-yellow-400 shadow-yellow-400/60',
        idle: 'ring-gray-600 shadow-transparent',
      }[status]

  const bgColor = isCamera
    ? 'bg-black/70'
    : {
        active: 'bg-green-500/30',
        pending: 'bg-yellow-400/30',
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

  // Tooltip for the pending state depends on whether auto-activate is enabled
  // for this specific socket — operator sees the configured behaviour.
  const autoEnabled = !isCamera && !isWater && socketId !== null
    ? !!socketAutoActivate[`${pedestalId}-${socketId}`]
    : false

  // v3.8 — show a small red lightning bolt when this socket's breaker is
  // tripped. Purely additive; the existing ring/bg colour logic is untouched.
  const breakerTripped = !isCamera && !isWater && socketId !== null
    ? socketBreakerStates[`${pedestalId}-${socketId}`]?.breaker_state === 'tripped'
    : false

  const tooltipText = isCamera
    ? 'Camera'
    : status === 'active'
      ? 'Stop Session'
      : status === 'pending'
        ? (autoEnabled
          ? 'Plug inserted — auto-activating in 2s'
          : 'Plug inserted — awaiting activation')
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
        {breakerTripped && (
          <span
            aria-label="Breaker tripped"
            title="Breaker tripped"
            className="absolute -top-1 -right-1 text-red-500 text-base drop-shadow animate-pulse pointer-events-none"
          >
            ⚡
          </span>
        )}
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
  // v3.30 — this panel is INFORMATION-ONLY. All control (activate/stop/approve/
  // reject) lives in the Control Center; clicking a socket only surfaces its
  // state, live readings, session counter, and the pedestal's Smart Mode.
  const { pendingSessions, activeSessions, socketLiveData, pendingSockets, optaWaterStates, socketComputedStates, socketBreakerStates, socketLoadStates, socketHardwareConfig, optaStatusInfo, pedestalHealth } = useStore()
  const isAdmin = useAuthStore((s) => s.role) === 'admin'
  const [histOpen, setHistOpen] = useState(false)

  const isWater = zoneId === 'water-left' || zoneId === 'water-right'
  const isCamera = zoneId === 'camera'
  const socketId = typeof zoneId === 'number' ? zoneId : null
  const valveName = zoneId === 'water-left' ? 'V1' : zoneId === 'water-right' ? 'V2' : null
  const valveState = valveName ? optaWaterStates[`${pedestalId}-${valveName}`] : null
  const socketPending = !isWater && !isCamera && socketId !== null
    ? !!pendingSockets[`${pedestalId}-${socketId}`]
    : false

  // Camera zone is handled by modal; this panel shouldn't appear for it
  if (isCamera) return null
  const zone = SOCKET_ZONES.find((z) => z.id === zoneId)!

  // v3.30 — Smart Mode indicator: live opta_status first, health snapshot fallback.
  const smartMode = optaStatusInfo[pedestalId]?.smart_mode ?? pedestalHealth[pedestalId]?.smart_mode ?? false

  // Water sessions are tracked per-valve via firmware state. Since backend
  // session rows use socket_id=None for water (shared V1/V2), use the live
  // opta_water_status stream to distinguish which valve is active.
  const pendingSession = isWater
    ? undefined
    : pendingSessions.find((s) => s.pedestal_id === pedestalId && s.socket_id === socketId && s.type === 'electricity')

  const activeSession = isWater
    ? undefined
    : activeSessions.find((s) => s.pedestal_id === pedestalId && s.socket_id === socketId && s.type === 'electricity')

  const waterActive = isWater && valveState?.state === 'active'
  const isActive = !!activeSession || waterActive

  const liveData = !isWater && socketId ? socketLiveData[socketId] : null

  // Hardware-level state (same sources the Command Center uses) so the panel
  // reflects breaker/fault/meter reality instead of only session inference.
  const skey = socketId !== null ? `${pedestalId}-${socketId}` : ''
  const breakerState = !isWater && socketId !== null ? socketBreakerStates[skey]?.breaker_state : undefined
  const breakerTripped = breakerState === 'tripped'
  const computedState = !isWater && socketId !== null ? socketComputedStates[skey] : undefined
  const isFault = computedState === 'fault'
  const loadState = !isWater && socketId !== null ? socketLoadStates[skey] : undefined
  const hwConfig = !isWater && socketId !== null ? socketHardwareConfig[skey] : undefined

  return (
    <div className="card space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`w-4 h-4 rounded-full ${
            breakerTripped || isFault ? 'bg-red-400 animate-pulse' :
            isActive ? 'bg-green-400 animate-pulse' :
            pendingSession ? 'bg-amber-400 animate-pulse' : 'bg-gray-600'
          }`} />
          <h3 className="text-lg font-bold text-white">{zone.label}</h3>
          <span className={
            breakerTripped || isFault ? 'badge bg-red-900/40 text-red-300 border border-red-700/50' :
            isActive ? 'badge-active' :
            pendingSession ? 'badge-pending' :
            'badge bg-gray-800 text-gray-500'
          }>
            {breakerTripped ? 'Breaker Tripped' : isFault ? 'Fault' : isActive ? 'Active' : pendingSession ? 'Starting…' : 'Idle'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setHistOpen(true)}
            className="text-[10px] px-1.5 py-0.5 rounded border border-gray-600 text-gray-300 hover:bg-gray-700/60"
            title="Usage history + monthly report"
          >
            History
          </button>
          {/* v3.30 — Smart Mode at a glance. OFF = standalone (Opta in control). */}
          <span
            className={`badge text-[10px] ${smartMode
              ? 'bg-green-900/40 text-green-300 border border-green-700/50'
              : 'bg-gray-800 text-gray-400 border border-gray-700'}`}
            title={smartMode
              ? 'Smart Mode ON — the NUC controls this pedestal.'
              : 'Smart Mode OFF — standalone; the Opta controls this pedestal (dashboard read-only).'}
          >
            {smartMode ? 'Smart Mode: ON' : 'Smart Mode: OFF'}
          </span>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-xl leading-none">✕</button>
        </div>
      </div>

      {/* Breaker tripped — highest priority; mirrors the ⚡ marker on the socket */}
      {breakerTripped && (
        <div className="bg-red-900/20 border border-red-700/50 rounded-lg p-4 space-y-2">
          <p className="text-red-300 font-medium">⚡ Breaker tripped{socketId !== null ? ` — Q${socketId}` : ''}</p>
          <p className="text-xs text-gray-400">
            This socket's circuit breaker has tripped — no power is being delivered.
            Reset it from the Control Center (Breaker panel).
          </p>
          {hwConfig?.rated_amps != null && (
            <p className="text-xs text-gray-500">
              Rated: {hwConfig.rated_amps} A{hwConfig.meter_type ? ` · ${hwConfig.meter_type}` : ''}
            </p>
          )}
        </div>
      )}

      {/* Fault (computed hardware state) */}
      {!breakerTripped && isFault && (
        <div className="bg-red-900/20 border border-red-700/50 rounded-lg p-4 space-y-2">
          <p className="text-red-300 font-medium">Socket fault</p>
          <p className="text-xs text-gray-400">
            The pedestal reports a hardware fault on this socket. Check the Control Center
            and diagnostics for details.
          </p>
        </div>
      )}

      {/* Socket-level pending: device connected, awaiting approval (info-only) */}
      {socketPending && !pendingSession && !isActive && !breakerTripped && !isFault && (
        <div className="bg-amber-900/20 border border-amber-700/40 rounded-lg p-4 space-y-1">
          <p className="text-amber-300 font-medium">Device Connected — Awaiting Approval</p>
          <p className="text-xs text-gray-400">
            A device was plugged in. Approve or reject it from the Control Center.
          </p>
        </div>
      )}

      {/* Pending state (transient — session is activating via DB pending) */}
      {pendingSession && !isActive && !breakerTripped && !isFault && (
        <div className="bg-amber-900/20 border border-amber-700/40 rounded-lg p-4 space-y-2">
          <p className="text-amber-300 font-medium">Session starting…</p>
          {pendingSession.customer_name && (
            <p className="text-sm text-blue-300 font-medium">Customer: {pendingSession.customer_name}</p>
          )}
        </div>
      )}

      {/* Active state — live readings + session counter (info-only) */}
      {isActive && !breakerTripped && !isFault && (
        <div className="bg-green-900/20 border border-green-700/40 rounded-lg p-4 space-y-3">
          {!isWater && liveData && (
            <>
              <LiveMetric label="Power" value={`${liveData.watts.toFixed(0)} W`} big />
              <LiveMetric label="Total Energy" value={`${liveData.kwh_total.toFixed(4)} kWh`} />
            </>
          )}
          {!isWater && loadState && (loadState.voltage_v != null || loadState.current_amps != null || loadState.power_factor != null) && (
            <>
              {loadState.voltage_v != null && <LiveMetric label="Voltage" value={`${loadState.voltage_v.toFixed(0)} V`} />}
              {loadState.current_amps != null && <LiveMetric label="Current" value={`${loadState.current_amps.toFixed(1)} A`} />}
              {loadState.power_factor != null && <LiveMetric label="Power factor" value={loadState.power_factor.toFixed(2)} />}
            </>
          )}
          {isWater && valveState && (
            <>
              <LiveMetric label="Session Volume" value={`${(valveState.session_l ?? 0).toFixed(2)} L`} big />
              <LiveMetric label="Total" value={`${(valveState.total_l ?? 0).toFixed(2)} L`} />
            </>
          )}
          {activeSession && <SessionTimer startedAt={activeSession.started_at} />}
        </div>
      )}

      {/* Idle state */}
      {!socketPending && !pendingSession && !isActive && !breakerTripped && !isFault && (
        <div className="space-y-3">
          <div className="text-center py-6 text-gray-500">
            <p className="text-4xl mb-3">{isWater ? '💧' : '🔌'}</p>
            <p>{isWater ? 'No water flow detected' : 'No device connected'}</p>
            <p className="text-xs mt-1">Waiting for connection…</p>
          </div>
          {!isWater && (breakerState || hwConfig?.meter_type || hwConfig?.rated_amps != null) && (
            <div className="bg-gray-800/40 border border-gray-700/50 rounded-lg p-3 text-xs text-gray-400 space-y-1">
              {breakerState && (
                <div className="flex justify-between"><span>Breaker</span><span className="text-gray-300 capitalize">{breakerState}</span></div>
              )}
              {hwConfig?.meter_type && (
                <div className="flex justify-between"><span>Meter</span><span className="text-gray-300">{hwConfig.meter_type}</span></div>
              )}
              {hwConfig?.rated_amps != null && (
                <div className="flex justify-between"><span>Rated</span><span className="text-gray-300">{hwConfig.rated_amps} A</span></div>
              )}
            </div>
          )}
        </div>
      )}

      {/* v3.30 — controls moved out: this panel is read-only. */}
      <p className="text-[11px] text-gray-500 border-t border-gray-700/50 pt-2">
        Controls (activate, stop, approve/reject) are in the Control Center.
      </p>

      {histOpen && (
        <SocketUsageHistoryModal
          pedestalId={pedestalId}
          socketId={isWater ? (valveName ? Number(valveName.replace('V', '')) : 0) : (socketId ?? 0)}
          resource={isWater ? 'water' : 'electricity'}
          label={isWater ? (valveName ?? 'V?') : (socketId !== null ? `Q${socketId}` : '?')}
          isAdmin={isAdmin}
          onClose={() => setHistOpen(false)}
        />
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
