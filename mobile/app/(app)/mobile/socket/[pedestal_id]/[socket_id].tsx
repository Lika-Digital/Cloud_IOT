/**
 * QR-scan landing page (v3.6 — mobile monitoring-only).
 *
 * Flow:
 *   1. On mount, POST /api/mobile/qr/claim with the path params.
 *   2. Switch on `status`:
 *        - no_session    → show socket-state view, poll /live every 5 s.
 *        - claimed       → connect WS with websocket_token, live meter.
 *        - already_owner → same as claimed but don't re-call claim on retry.
 *        - read_only     → live meter, no controls, "managed by another user".
 *   3. On `session_ended` WS event, show summary and stop.
 *
 * NOTE: customer stop is DISABLED on the backend (403). This page never
 * renders a Stop button. The only way to end a session is to unplug the
 * cable (firmware UserPluggedOut) or wait for the operator.
 */
import { useEffect, useRef, useState } from 'react'
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native'
import { useLocalSearchParams } from 'expo-router'
import { qrClaim, sessionLive, type QrClaimResponse, type SessionLiveResponse } from '../../../../src/api/mobile'

type ViewState = 'loading' | 'no_session' | 'claimed' | 'read_only' | 'ended' | 'error'

interface LiveMetrics {
  duration_seconds: number
  energy_kwh: number
  power_kw: number
}


export default function QrSocketLanding() {
  const params = useLocalSearchParams<{ pedestal_id: string; socket_id: string }>()
  const pedestalId = Array.isArray(params.pedestal_id) ? params.pedestal_id[0] : params.pedestal_id
  const socketId = Array.isArray(params.socket_id) ? params.socket_id[0] : params.socket_id

  const [view, setView] = useState<ViewState>('loading')
  const [claim, setClaim] = useState<QrClaimResponse | null>(null)
  const [metrics, setMetrics] = useState<LiveMetrics | null>(null)
  const [errMsg, setErrMsg] = useState<string>('')

  const wsRef = useRef<WebSocket | null>(null)
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Step 1 — claim on mount.
  useEffect(() => {
    if (!pedestalId || !socketId) {
      setErrMsg('Missing pedestal or socket from QR code')
      setView('error')
      return
    }
    qrClaim(pedestalId, socketId)
      .then((res) => {
        setClaim(res)
        if (res.status === 'no_session') {
          setView('no_session')
        } else {
          setMetrics({
            duration_seconds: res.duration_seconds,
            energy_kwh: res.energy_kwh,
            power_kw: res.power_kw,
          })
          setView(res.status === 'read_only' ? 'read_only' : 'claimed')
        }
      })
      .catch((e) => {
        const detail = e?.response?.data?.detail ?? 'Could not claim this socket'
        setErrMsg(typeof detail === 'string' ? detail : 'Error')
        setView('error')
      })
  }, [pedestalId, socketId])

  // Step 2a — WebSocket subscription when we have a session.
  useEffect(() => {
    if (!claim || claim.status === 'no_session') return
    const token = claim.websocket_token
    const host = (process.env.EXPO_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws')
    const wsUrl = host.includes('?') ? `${host}&token=${token}` : `${host}?token=${token}`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data)
        if (msg?.event === 'session_telemetry' && msg?.data) {
          setMetrics({
            duration_seconds: msg.data.duration_seconds,
            energy_kwh: msg.data.energy_kwh,
            power_kw: msg.data.power_kw,
          })
        } else if (msg?.event === 'session_ended') {
          setView('ended')
          setMetrics((m) => m && { ...m, power_kw: 0 })
          ws.close()
        } else if (msg?.event === 'socket_state_changed' && msg?.data?.state) {
          // no-op for now; useful if we later surface fault → error state.
        }
      } catch { /* ignore malformed frames */ }
    }
    ws.onerror = () => { /* silent — fall back to REST polling below */ }
    return () => { try { ws.close() } catch { /* noop */ } }
  }, [claim])

  // Step 2b — REST polling fallback every 5 s whenever there's an active session.
  useEffect(() => {
    if (view !== 'claimed' && view !== 'read_only') return
    if (!claim || claim.status === 'no_session') return
    const sid = claim.session_id
    pollTimerRef.current = setInterval(() => {
      sessionLive(sid)
        .then((m: SessionLiveResponse) => setMetrics({
          duration_seconds: m.duration_seconds,
          energy_kwh: m.energy_kwh,
          power_kw: m.power_kw,
        }))
        .catch(() => { /* non-fatal; WS may still be delivering */ })
    }, 5000)
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }, [view, claim])

  // Step 3 — "no_session" polling to detect auto-activation without re-scan.
  useEffect(() => {
    if (view !== 'no_session') return
    const t = setInterval(() => {
      if (!pedestalId || !socketId) return
      qrClaim(pedestalId, socketId).then((res) => {
        if (res.status !== 'no_session') {
          setClaim(res)
          setMetrics({
            duration_seconds: res.duration_seconds,
            energy_kwh: res.energy_kwh,
            power_kw: res.power_kw,
          })
          setView(res.status === 'read_only' ? 'read_only' : 'claimed')
        }
      }).catch(() => { /* stay in no_session */ })
    }, 5000)
    return () => clearInterval(t)
  }, [view, pedestalId, socketId])

  // ── Render ────────────────────────────────────────────────────────────────

  if (view === 'loading') {
    return <Center><ActivityIndicator /></Center>
  }
  if (view === 'error') {
    return <Center><Text style={styles.err}>{errMsg}</Text></Center>
  }
  if (view === 'no_session' && claim?.status === 'no_session') {
    return (
      <Center>
        <Text style={styles.title}>{`Socket ${socketId}`}</Text>
        <Text style={styles.sub}>{`Pedestal ${pedestalId}`}</Text>
        <Text style={styles.state}>
          {claim.socket_state === 'pending'
            ? 'Cable detected — awaiting activation'
            : 'No session on this socket yet. Plug in a cable to start.'}
        </Text>
        <Text style={styles.hint}>Checking every 5 s…</Text>
      </Center>
    )
  }
  if (view === 'ended') {
    return (
      <Center>
        <Text style={styles.title}>Session ended</Text>
        {metrics && (
          <>
            <Metric label="Total energy" value={`${metrics.energy_kwh.toFixed(3)} kWh`} />
            <Metric label="Duration" value={formatDuration(metrics.duration_seconds)} />
          </>
        )}
        <Text style={styles.hint}>Thank you. Unplug the cable to finalise.</Text>
      </Center>
    )
  }
  const readOnly = view === 'read_only'
  return (
    <Center>
      <Text style={styles.title}>{`Socket ${socketId}`}</Text>
      <Text style={styles.sub}>{`Pedestal ${pedestalId}`}</Text>
      {readOnly && (
        <Text style={styles.warn}>This session is managed by another user.</Text>
      )}
      {metrics && (
        <>
          <Metric label="Power" value={`${metrics.power_kw.toFixed(2)} kW`} />
          <Metric label="Energy" value={`${metrics.energy_kwh.toFixed(3)} kWh`} />
          <Metric label="Duration" value={formatDuration(metrics.duration_seconds)} />
        </>
      )}
      <Text style={styles.hint}>
        {'Unplug the cable when you are finished — operator-stop is also available from the dashboard.'}
      </Text>
    </Center>
  )
}


function Center({ children }: { children: React.ReactNode }) {
  return <View style={styles.center}>{children}</View>
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metric}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue}>{value}</Text>
    </View>
  )
}

function formatDuration(s: number): string {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}h ${m}m ${sec}s`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}


const styles = StyleSheet.create({
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 20, gap: 8 },
  title: { fontSize: 22, fontWeight: 'bold' },
  sub: { fontSize: 14, opacity: 0.6 },
  state: { fontSize: 15, marginTop: 16, textAlign: 'center' },
  hint: { marginTop: 24, fontSize: 12, opacity: 0.5, textAlign: 'center' },
  err: { color: '#c00', fontSize: 14, textAlign: 'center' },
  warn: { color: '#b78000', fontSize: 13, marginTop: 8, textAlign: 'center' },
  metric: { alignItems: 'center', marginTop: 12 },
  metricLabel: { fontSize: 11, opacity: 0.6, textTransform: 'uppercase' },
  metricValue: { fontSize: 24, fontWeight: '600', marginTop: 2 },
})
