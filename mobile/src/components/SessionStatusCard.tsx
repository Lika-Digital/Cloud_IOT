import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native'
import { useSessionStore } from '../store/sessionStore'

interface Props {
  onStartPress: () => void
  onStopPress: () => void
  stopping: boolean
}

export function SessionStatusCard({ onStartPress, onStopPress, stopping }: Props) {
  const { activeSession, liveWatts, liveKwh, liveLpm, liveLiters } = useSessionStore()

  if (!activeSession) {
    return (
      <View style={styles.card}>
        <Text style={styles.idleIcon}>🔌</Text>
        <Text style={styles.idleText}>No active session</Text>
        <TouchableOpacity style={styles.startBtn} onPress={onStartPress}>
          <Text style={styles.startBtnText}>Start Session</Text>
        </TouchableOpacity>
      </View>
    )
  }

  if (activeSession.status === 'pending') {
    return (
      <View style={[styles.card, styles.pendingCard]}>
        <ActivityIndicator color="#f59e0b" size="large" />
        <Text style={styles.pendingTitle}>Awaiting approval</Text>
        <Text style={styles.pendingSubtitle}>The marina operator will approve your session shortly.</Text>
      </View>
    )
  }

  const isElec = activeSession.type === 'electricity'

  return (
    <View style={[styles.card, styles.activeCard]}>
      <View style={styles.statusRow}>
        <View style={styles.activeDot} />
        <Text style={styles.activeTitle}>Session Active</Text>
      </View>
      <View style={styles.metricsRow}>
        {isElec ? (
          <>
            <Metric label="Power" value={`${liveWatts.toFixed(0)} W`} />
            <Metric label="Energy" value={`${liveKwh.toFixed(4)} kWh`} />
          </>
        ) : (
          <>
            <Metric label="Flow" value={`${liveLpm.toFixed(1)} L/min`} />
            <Metric label="Total" value={`${liveLiters.toFixed(2)} L`} />
          </>
        )}
      </View>
      <TouchableOpacity style={styles.stopBtn} onPress={onStopPress} disabled={stopping}>
        {stopping ? <ActivityIndicator color="#fff" /> : <Text style={styles.stopBtnText}>Stop Session</Text>}
      </TouchableOpacity>
    </View>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metric}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue}>{value}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#1f2937',
    borderRadius: 16,
    padding: 24,
    alignItems: 'center',
    gap: 12,
  },
  idleIcon: { fontSize: 48 },
  idleText: { color: '#9ca3af', fontSize: 16 },
  startBtn: {
    backgroundColor: '#2563eb',
    paddingHorizontal: 32,
    paddingVertical: 12,
    borderRadius: 10,
    marginTop: 8,
  },
  startBtnText: { color: '#fff', fontWeight: '700', fontSize: 16 },
  pendingCard: { borderWidth: 1, borderColor: '#d97706' },
  pendingTitle: { color: '#f59e0b', fontWeight: '700', fontSize: 18 },
  pendingSubtitle: { color: '#6b7280', textAlign: 'center', fontSize: 14 },
  activeCard: { borderWidth: 1, borderColor: '#16a34a' },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  activeDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: '#4ade80' },
  activeTitle: { color: '#4ade80', fontWeight: '700', fontSize: 18 },
  metricsRow: { flexDirection: 'row', gap: 32, marginTop: 8 },
  metric: { alignItems: 'center' },
  metricLabel: { color: '#9ca3af', fontSize: 12 },
  metricValue: { color: '#fff', fontWeight: '700', fontSize: 20, fontFamily: 'monospace' },
  stopBtn: {
    backgroundColor: '#dc2626',
    paddingHorizontal: 32,
    paddingVertical: 12,
    borderRadius: 10,
    marginTop: 8,
  },
  stopBtnText: { color: '#fff', fontWeight: '700', fontSize: 16 },
})
