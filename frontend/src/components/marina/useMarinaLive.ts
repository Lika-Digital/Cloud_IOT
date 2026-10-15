import { useEffect, useMemo, useRef, useState } from 'react'
import type { MarinaCore } from '../../api/marina'
import { onWsMessage } from '../../hooks/wsBus'
import { useStore } from '../../store'

/**
 * /marina on the websocket (block 4, 2026-10-15; §5 "live values arrive by websocket, structure
 * arrives by REST"; decision 8 — allowed since part B strips identity from the broadcast).
 *
 *  - LIVE FIGURES from the socket: a row's amps from `meter_telemetry_received`, a valve's
 *    L/min from `water_reading`. CORE never carries L/min (it is null by design), so without
 *    this the water line has no flow figure at all.
 *  - STRUCTURE from REST: an event that changes a state, a session or an alarm re-fetches CORE,
 *    once per burst (debounced), because status is computed on the server and nowhere else.
 *    MEASURED in mqtt_handlers.py: `socket_state_changed` is broadcast on EVERY socket status
 *    message, changed or not (and `opta_status` / `pedestal_health_updated` on every cabinet
 *    heartbeat), so a state report re-fetches only when it DIFFERS from what CORE last said —
 *    otherwise the dashboard would re-fetch at the cabinet's reporting rate, the very load
 *    §5 rejects. A cabinet that goes silent sends nothing; the 60 s re-fetch catches it.
 *  - POLLING only as a fallback: every 15 s while the socket is down (the old behaviour), once a
 *    minute while it is up, in case an event was missed.
 *
 * A live figure follows the server's own rules: shown only while the outlet is in use (CORE
 * amps is null on an idle socket), and only for 60 s after it arrived — OUTLET_STALE_S, the
 * window after which CORE stops showing a figure as "now".
 */
export const LIVE_FRESH_MS = 60_000
const POLL_DOWN_MS = 15_000
const POLL_UP_MS = 60_000
const DEBOUNCE_MS = 1_000

/** Events that are themselves a change: a session, an alarm, a breaker, a load verdict. */
const STRUCTURAL = new Set([
  'session_created', 'session_updated', 'session_completed',
  'alarm_triggered', 'alarm_acknowledged', 'alarm_resolved', 'hardware_alarm',
  'breaker_state_changed', 'breaker_alarm', 'berth_occupancy_updated',
  'meter_load_warning', 'meter_load_critical', 'meter_load_resolved', 'meter_load_auto_stop',
  'meter_load_auto_stop_acknowledged', 'valve_flow_warning', 'led_changed', 'marina_ack',
])

/** What CORE last said about each outlet's state, keyed "1:Q3" / "1:V1". */
function coreStates(core: MarinaCore | null): Map<string, string> {
  const m = new Map<string, string>()
  for (const p of core?.pedestals ?? []) {
    for (const b of p.berths) if (b.power.outlet) m.set(`${p.pedestal_id}:${b.power.outlet}`, b.power.state)
    for (const w of p.water_outlets) m.set(`${p.pedestal_id}:${w.outlet}`, w.state)
  }
  return m
}

type Reading = { value: number; at: number }

export function useMarinaLive(load: () => void, core: MarinaCore | null) {
  const connected = useStore((s) => s.wsConnected)
  const [live, setLive] = useState<Map<string, Reading>>(() => new Map())
  const [now, setNow] = useState(() => Date.now())
  // The last state per outlet: CORE's, updated by each report, so only a difference re-fetches.
  const states = useRef<Map<string, string>>(new Map())
  useEffect(() => { states.current = coreStates(core) }, [core])

  useEffect(() => {
    const t = setInterval(load, connected ? POLL_UP_MS : POLL_DOWN_MS)
    return () => clearInterval(t)
  }, [load, connected])

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null
    const put = (key: string, value: unknown) => {
      if (typeof value !== 'number' || !Number.isFinite(value)) return
      setLive((prev) => new Map(prev).set(key, { value, at: Date.now() }))
    }
    const refetch = () => {
      if (timer === null) timer = setTimeout(() => { timer = null; load() }, DEBOUNCE_MS)
    }
    /** A state report: re-fetch only if it differs from the last known state of that outlet. */
    const reported = (key: string, state: unknown) => {
      if (typeof state !== 'string') return
      const was = states.current.get(key)
      states.current.set(key, state)
      if (was !== undefined && was !== state) refetch()
    }
    const off = onWsMessage(({ event, data }) => {
      const pid = data?.pedestal_id
      if (event === 'socket_state_changed' && typeof pid === 'number' && typeof data.socket_id === 'number') {
        reported(`${pid}:Q${data.socket_id}`, data.state)
      } else if (event === 'opta_water_status' && typeof pid === 'number' && typeof data.valve_name === 'string') {
        reported(`${pid}:${data.valve_name}`, data.state)
      } else if (event === 'meter_telemetry_received' && typeof pid === 'number' && typeof data.socket_id === 'number') {
        put(`${pid}:Q${data.socket_id}`, data.current_amps)
      } else if (event === 'water_reading' && typeof pid === 'number' && typeof data.valve_id === 'number') {
        put(`${pid}:V${data.valve_id}`, data.lpm)
      } else if (STRUCTURAL.has(event)) {
        refetch()
      }
    })
    return () => { off(); if (timer) clearTimeout(timer) }
  }, [load])

  // Re-render so a figure that stops arriving goes back to CORE's value (a dash), not frozen.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 5_000)
    return () => clearInterval(t)
  }, [])

  return { connected, live, now }
}

/** CORE with the fresh live figures laid over it — only where CORE says the outlet is in use. */
export function withLive(core: MarinaCore | null, live: Map<string, Reading>, now: number): MarinaCore | null {
  if (!core || live.size === 0) return core
  const fresh = (key: string) => {
    const r = live.get(key)
    return r && now - r.at <= LIVE_FRESH_MS ? r.value : undefined
  }
  return {
    ...core,
    pedestals: core.pedestals.map((p) => ({
      ...p,
      berths: p.berths.map((b) => {
        const v = b.power.outlet && b.power.state === 'active' ? fresh(`${p.pedestal_id}:${b.power.outlet}`) : undefined
        return v === undefined ? b : { ...b, power: { ...b.power, amps: Math.round(v * 100) / 100 } }
      }),
      water_outlets: p.water_outlets.map((w) => {
        const v = w.on ? fresh(`${p.pedestal_id}:${w.outlet}`) : undefined
        return v === undefined ? w : { ...w, litres_per_min: Math.round(v * 10) / 10 }
      }),
    })),
  }
}

export function useLiveCore(core: MarinaCore | null, live: Map<string, Reading>, now: number) {
  return useMemo(() => withLive(core, live, now), [core, live, now])
}
