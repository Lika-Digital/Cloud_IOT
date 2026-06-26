import { useCallback, useEffect, useRef, useState } from 'react'
import {
  View, Text, TouchableOpacity, StyleSheet, ActivityIndicator, ScrollView, Alert,
} from 'react-native'
import { useAuthStore } from '../../src/store/authStore'
import { useSessionStore } from '../../src/store/sessionStore'
import { useTheme } from '../../src/hooks/useTheme'
import { useNfc } from '../../src/hooks/useNfc'
import {
  nfcScan, stopNfcSession, getNfcSession, erpApiKeyConfigured, socketLabelToNumber,
  type NfcScanResult,
} from '../../src/api/nfc'

// NFC charging — Scan tab.
// 1) Tap "Scan tag" → read the pedestal socket's NFC tag UID.
// 2) POST /api/nfc/scan (ERP key) pre-registers the charge (5-min window).
// 3) Plug in the cable → backend activates (Smart Mode ON) and broadcasts
//    session_created; the WS hook adopts it into the session store.
// 4) Live energy/power stream in over the existing WebSocket.

function fmtCountdown(ms: number): string {
  if (ms <= 0) return '0:00'
  const s = Math.floor(ms / 1000)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export default function ScanScreen() {
  const t = useTheme()
  const profile = useAuthStore((s) => s.profile)
  const { activeSession, liveWatts, liveKwh, nfcPending, setNfcPending, setActiveSession, clearLive } =
    useSessionStore()
  const { supported, scanning, readTagUid, cancel } = useNfc()

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastUid, setLastUid] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())
  const [estCost, setEstCost] = useState<number | null>(null)
  const [stopping, setStopping] = useState(false)

  const keyOk = erpApiKeyConfigured()
  const userId = profile?.email || (profile?.id != null ? String(profile.id) : '')

  // 1s ticker drives the pending countdown + expiry cleanup.
  useEffect(() => {
    const iv = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(iv)
  }, [])

  // Expire a stale pending scan (no plug-in within the window).
  useEffect(() => {
    if (nfcPending && !activeSession) {
      const left = new Date(nfcPending.expires_at).getTime() - now
      if (left <= 0) {
        setNfcPending(null)
        setError('Scan expired — no plug-in detected. Scan the tag again.')
      }
    }
  }, [now, nfcPending, activeSession, setNfcPending])

  // While active, poll the authoritative NFC status for the estimated cost.
  useEffect(() => {
    if (!activeSession) {
      setEstCost(null)
      return
    }
    let active = true
    const poll = () =>
      getNfcSession(activeSession.id)
        .then((s) => { if (active) setEstCost(s.estimated_cost) })
        .catch(() => { /* non-fatal */ })
    poll()
    const iv = setInterval(poll, 15_000)
    return () => { active = false; clearInterval(iv) }
  }, [activeSession])

  const handleScan = useCallback(async () => {
    setError(null)
    if (!keyOk) {
      setError('ERP API key not configured. Set EXPO_PUBLIC_ERP_API_KEY in mobile/.env.')
      return
    }
    if (!userId) {
      setError('No customer profile loaded — please sign in again.')
      return
    }
    setBusy(true)
    let uid: string
    try {
      uid = await readTagUid()
      setLastUid(uid)
    } catch (e: any) {
      setBusy(false)
      setError(e?.message ?? 'Could not read the tag. Try again.')
      return
    }
    try {
      const res: NfcScanResult = await nfcScan(uid, userId)
      setNfcPending({
        cabinet_id: res.cabinet_id,
        socket_id: res.socket_id,
        socketNum: socketLabelToNumber(res.socket_id),
        user_id: userId,
        expires_at: res.expires_at,
      })
    } catch (e: any) {
      const status = e?.response?.status
      const detail = e?.response?.data?.detail
      if (status === 404) setError(`Tag not provisioned (UID ${uid}). Ask an operator to register it to a socket.`)
      else if (status === 409) setError('That socket is already in use. Try another, or wait.')
      else if (status === 503) setError('Socket unavailable (fault or service down). Try again later.')
      else if (status === 401) setError('ERP API key rejected — check EXPO_PUBLIC_ERP_API_KEY.')
      else setError(detail ?? 'Scan failed. Check connection to the NUC and try again.')
    } finally {
      setBusy(false)
    }
  }, [keyOk, userId, readTagUid, setNfcPending])

  const handleStop = useCallback(async () => {
    if (!activeSession) return
    setStopping(true)
    try {
      await stopNfcSession(activeSession.id)
      // The WS session_completed event clears activeSession; do it eagerly too.
      setActiveSession(null)
      clearLive()
    } catch (e: any) {
      const status = e?.response?.status
      if (status === 409) Alert.alert('Already stopped', 'This session was already ended by the operator.')
      else Alert.alert('Stop failed', 'Could not stop the session. You can also unplug the cable.')
    } finally {
      setStopping(false)
    }
  }, [activeSession, setActiveSession, clearLive])

  const s = makeStyles(t)

  // ── Active session ──────────────────────────────────────────────────────────
  if (activeSession) {
    return (
      <ScrollView style={s.screen} contentContainerStyle={s.content}>
        <Text style={s.h1}>Charging</Text>
        <View style={[s.card, { borderColor: t.success, borderWidth: 1 }]}>
          <View style={s.row}>
            <View style={[s.dot, { backgroundColor: t.success }]} />
            <Text style={[s.cardTitle, { color: t.success }]}>Session active</Text>
          </View>
          <Text style={s.muted}>
            Socket {activeSession.socket_id ?? '—'} · pedestal {activeSession.pedestal_id}
          </Text>
          <View style={s.metricsRow}>
            <Metric t={t} label="Power" value={`${liveWatts.toFixed(0)} W`} />
            <Metric t={t} label="Energy" value={`${liveKwh.toFixed(4)} kWh`} />
            <Metric t={t} label="Est. cost" value={estCost != null ? `€${estCost.toFixed(2)}` : '—'} />
          </View>
          <TouchableOpacity style={[s.btn, { backgroundColor: t.danger }]} onPress={handleStop} disabled={stopping}>
            {stopping ? <ActivityIndicator color="#fff" /> : <Text style={s.btnText}>Stop session</Text>}
          </TouchableOpacity>
          <Text style={s.hint}>Unplugging the cable also ends the session.</Text>
        </View>
      </ScrollView>
    )
  }

  // ── Waiting for plug-in ─────────────────────────────────────────────────────
  if (nfcPending) {
    const left = new Date(nfcPending.expires_at).getTime() - now
    return (
      <ScrollView style={s.screen} contentContainerStyle={s.content}>
        <Text style={s.h1}>Tag accepted</Text>
        <View style={[s.card, { borderColor: t.warning, borderWidth: 1 }]}>
          <ActivityIndicator color={t.warning} size="large" />
          <Text style={[s.cardTitle, { color: t.warning }]}>Plug in your cable</Text>
          <Text style={s.muted}>
            Socket {nfcPending.socket_id} · {nfcPending.cabinet_id}
          </Text>
          <Text style={s.countdown}>{fmtCountdown(left)}</Text>
          <Text style={s.hint}>
            Connect the cable to start charging. Activation needs the pedestal in Smart Mode — if nothing
            happens, the operator may have Smart Mode off.
          </Text>
          <TouchableOpacity style={[s.btnOutline, { borderColor: t.border }]} onPress={() => setNfcPending(null)}>
            <Text style={[s.btnText, { color: t.textSecondary }]}>Cancel</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    )
  }

  // ── Idle / scan ─────────────────────────────────────────────────────────────
  return (
    <ScrollView style={s.screen} contentContainerStyle={s.content}>
      <Text style={s.h1}>Scan to charge</Text>
      <Text style={s.sub}>Hold your phone to the NFC tag on the pedestal socket.</Text>

      <View style={s.card}>
        <Text style={s.nfcIcon}>📡</Text>
        {supported === false && (
          <Text style={[s.warn, { color: t.warning }]}>
            NFC isn’t available here. Use a physical phone with a custom dev build (not Expo Go / web).
          </Text>
        )}
        {!keyOk && (
          <Text style={[s.warn, { color: t.warning }]}>
            ERP API key missing — set EXPO_PUBLIC_ERP_API_KEY in mobile/.env, then restart.
          </Text>
        )}
        <TouchableOpacity
          style={[s.btn, { backgroundColor: t.accent, opacity: supported === false || busy || scanning ? 0.5 : 1 }]}
          onPress={handleScan}
          disabled={supported === false || busy || scanning}
        >
          {busy || scanning ? <ActivityIndicator color="#fff" /> : <Text style={s.btnText}>Scan tag</Text>}
        </TouchableOpacity>
        {scanning && (
          <TouchableOpacity style={[s.btnOutline, { borderColor: t.border }]} onPress={cancel}>
            <Text style={[s.btnText, { color: t.textSecondary }]}>Cancel</Text>
          </TouchableOpacity>
        )}
        {error && <Text style={[s.error, { color: t.danger }]}>{error}</Text>}
        {lastUid && !error && <Text style={s.uidHint}>Last tag UID: {lastUid}</Text>}
      </View>
    </ScrollView>
  )
}

function Metric({ t, label, value }: { t: ReturnType<typeof useTheme>; label: string; value: string }) {
  return (
    <View style={{ alignItems: 'center' }}>
      <Text style={{ color: t.textMuted, fontSize: 12 }}>{label}</Text>
      <Text style={{ color: t.textPrimary, fontWeight: '700', fontSize: 18, fontFamily: 'monospace' }}>{value}</Text>
    </View>
  )
}

function makeStyles(t: ReturnType<typeof useTheme>) {
  return StyleSheet.create({
    screen: { flex: 1, backgroundColor: t.bg },
    content: { padding: 16, gap: 12 },
    h1: { color: t.textPrimary, fontSize: 24, fontWeight: '800' },
    sub: { color: t.textSecondary, fontSize: 14 },
    card: {
      backgroundColor: t.card, borderRadius: 16, padding: 24, alignItems: 'center', gap: 14,
      borderWidth: 1, borderColor: t.border,
    },
    cardTitle: { fontWeight: '700', fontSize: 18 },
    nfcIcon: { fontSize: 56 },
    row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
    dot: { width: 10, height: 10, borderRadius: 5 },
    muted: { color: t.textMuted, fontSize: 13 },
    metricsRow: { flexDirection: 'row', gap: 24, marginTop: 4 },
    countdown: { color: t.textPrimary, fontSize: 32, fontWeight: '800', fontFamily: 'monospace' },
    btn: { paddingHorizontal: 32, paddingVertical: 13, borderRadius: 10, minWidth: 180, alignItems: 'center' },
    btnOutline: { paddingHorizontal: 24, paddingVertical: 10, borderRadius: 10, borderWidth: 1, alignItems: 'center' },
    btnText: { color: '#fff', fontWeight: '700', fontSize: 16 },
    hint: { color: t.textMuted, fontSize: 12, textAlign: 'center' },
    warn: { fontSize: 13, textAlign: 'center', fontWeight: '600' },
    error: { fontSize: 13, textAlign: 'center', fontWeight: '600' },
    uidHint: { color: t.textMuted, fontSize: 11, fontFamily: 'monospace' },
  })
}
