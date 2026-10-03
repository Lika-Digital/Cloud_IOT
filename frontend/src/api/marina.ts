import axios from 'axios'
import { useAuthStore } from '../store/authStore'

/**
 * Marina Monitoring & Control profile — CORE.
 *
 * The whole L1 dashboard is one call plus websocket deltas. **The frontend computes no
 * status**: `status`, `status_sentence` and every `available` flag are decided server-side,
 * once, and consumed by the web UI, the mobile app and the ERP alike. There is nothing to
 * drift.
 *
 * SHAPE — electricity is per berth, water is per pedestal.
 * The Krk layout: one pedestal covers 4 berths for electricity, one socket each, and water
 * serves a maximum of 2 users at a time via 2 valves which are NOT piped to specific berths.
 * So `Berth` has `power` and deliberately has no `water` field — a per-berth water line would
 * read "Water OFF" on a berth whose occupant is using the valve at the far end of the cabinet.
 */

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) {
      useAuthStore.getState().logout()
      window.location.href = '/login'
    }
    return Promise.reject(error)
  },
)

/** Three states and no more. Anything else is a bug in the reduction, not a new state. */
export type BerthStatus = 'ok' | 'attention' | 'unknown'

/**
 * The eleven status codes. Kept as a union so a `switch` over them is exhaustive at compile
 * time — the *sentence* comes from the server, but code that branches on the condition
 * (sorting, icon choice) must fail to build when a code is added.
 */
export type StatusCode =
  | 'no_contact'
  | 'standalone'
  | 'outlet_silent'
  | 'water_leak'
  | 'too_hot'
  | 'auto_off_overload'
  | 'breaker_tripped'
  | 'guard_unreviewed'
  | 'measurement_missing'
  | 'vessel_mismatch'
  | 'ok'
  | 'unrecognised'

/** Why a control cannot be rendered. Two reasons, two different sentences. */
export type UnavailableReason = 'no_socket' | 'standalone' | null

export interface PowerFacility {
  /** 'Q1'..'Q4', or null when this berth has no electricity socket. */
  outlet: string | null
  on: boolean
  state: 'idle' | 'pending' | 'active' | 'fault' | 'unknown'
  /** null when idle or unknown — never 0, which would read as "measured nothing". */
  watts: number | null
  unit: string
  /** false => render a sentence and NO control element in the DOM. Not a disabled button. */
  available: boolean
  unavailable_reason: UnavailableReason
}

export interface WaterOutlet {
  /** 'V1' | 'V2'. A pool of two, shared across the whole cabinet. */
  outlet: string
  on: boolean
  /**
   * No 'pending'. That state means "physically connected, awaiting activation" and comes
   * from the socket's plug-in detection; the firmware has no valve analogue. 'unknown' means
   * the cabinet has not described this valve within 60 s.
   */
  state: 'idle' | 'active' | 'unknown'
  litres_per_min: number | null
  unit: string
  rated_liters_per_min: number | null
  in_use: boolean
  available: boolean
  unavailable_reason: UnavailableReason
}

export interface Berth {
  berth_id: number
  berth_number: number | null
  status: BerthStatus
  status_code: StatusCode
  /** null only when status is 'ok'. Never an error code — these are the approved sentences. */
  status_sentence: string | null
  /** Precedence rank. For sorting only; never displayed. */
  status_rank: number
  power: PowerFacility
  occupied: boolean
  /** Distinguished from `occupied` so "we do not know" can render differently from "empty". */
  occupied_known: boolean
  /** null when no reference photo is configured — not false, which would claim a mismatch. */
  vessel_matches: boolean | null
  vessel_match_configured: boolean
  alarm_count: number
}

export interface SharedFacility {
  on: boolean
  scope: 'pedestal'
  available: boolean
  unavailable_reason: UnavailableReason
}

export interface GuardBlock {
  /** 'unavailable' is a FAULT and must never render as 'off', which is a decision. */
  state: 'on' | 'off' | 'paused' | 'unavailable'
  sentence: string
  scope: 'pedestal'
}

export interface MarinaPedestal {
  pedestal_id: number
  cabinet_id: string | null
  dock: string | null
  /** From the in-memory heartbeat, never a stored column — a retained status message lies. */
  reachable: boolean
  smart_mode: boolean
  berths: Berth[]
  /** Pedestal-level: the valves are a pool, not mapped to berths. */
  water_outlets: WaterOutlet[]
  light: SharedFacility
  guard: GuardBlock
  alarm_count: number
}

export interface MarinaCore {
  pedestals: MarinaPedestal[]
}

export interface OutletSpec {
  outlet: string | null
  /** From the cabinet's own `opta/config/hardware`. null = it has not said, which is not 16. */
  rated_amps: number | null
  phases: number | null
  meter_type: string | null
}

export interface ConsumptionSummary {
  /** null when any contributing session was unmeasurable. The sum of a partial set is not it. */
  kwh: number | null
  source: 'register' | 'integrated_legacy' | 'unknown' | null
  note: string
}

export interface BerthDetail extends Berth {
  pedestal_id: number
  cabinet_id: string | null
  outlet_spec: OutletSpec
  consumption: ConsumptionSummary
  reference_image: string | null
  guard: GuardBlock
  guard_scope_note: string
}

export interface MarinaAlarm {
  alarm_id: number
  pedestal_id: number | null
  cabinet_id: string | null
  status_code: StatusCode
  /** A plain sentence. Never the raw alarm_type. */
  sentence: string
  severity: string | null
  raised_at: string | null
  resolved_at: string | null
  active: boolean
}

export interface BerthAssignmentRow {
  berth_id: number
  /** 1..4, or null for a berth with no electricity. No valve_id — water is not mapped. */
  socket_id: number | null
  assigned_at: string | null
  assigned_by: string | null
}

export const getMarinaCore = () =>
  api.get<MarinaCore>('/marina/berths').then((r) => r.data)

export const getBerthDetail = (berthId: number) =>
  api.get<BerthDetail>(`/marina/berths/${berthId}`).then((r) => r.data)

export const getMarinaAlarms = () =>
  api.get<{ alarms: MarinaAlarm[] }>('/marina/alarms').then((r) => r.data)

export const getBerthAssignments = (pedestalId: number) =>
  api.get<{ pedestal_id: number; assignments: BerthAssignmentRow[] }>(
    `/marina/berth-assignments/${pedestalId}`,
  ).then((r) => r.data)

export const putBerthAssignments = (
  pedestalId: number,
  assignments: { berth_id: number; socket_id: number | null }[],
) => api.put<{ pedestal_id: number; assignments: BerthAssignmentRow[] }>(
  `/marina/berth-assignments/${pedestalId}`, { assignments },
).then((r) => r.data)
