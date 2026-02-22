import { useState, useEffect } from 'react'
import { View, Text, StyleSheet, SafeAreaView, ScrollView } from 'react-native'
import { useAuthStore } from '../../src/store/authStore'
import { useSessionStore } from '../../src/store/sessionStore'
import { getMySessions } from '../../src/api/sessions'
import { SessionStatusCard } from '../../src/components/SessionStatusCard'
import { StartSessionModal } from '../../src/components/StartSessionModal'
import { useWebSocket } from '../../src/hooks/useWebSocket'
import { stopMySession } from '../../src/api/sessions'

export default function HomeScreen() {
  const { profile } = useAuthStore()
  const { setActiveSession, activeSession } = useSessionStore()
  const [showModal, setShowModal] = useState(false)
  const [stopping, setStopping] = useState(false)

  useWebSocket()

  useEffect(() => {
    // Restore active session on mount
    getMySessions().then((sessions) => {
      const active = sessions.find((s) => s.status === 'active' || s.status === 'pending')
      if (active) {
        setActiveSession({
          id: active.id,
          pedestal_id: active.pedestal_id,
          socket_id: active.socket_id,
          type: active.type as 'electricity' | 'water',
          status: active.status,
          started_at: active.started_at,
          customer_id: active.customer_id,
        })
      }
    }).catch(() => {})
  }, [])

  const handleStop = async () => {
    if (!activeSession) return
    setStopping(true)
    try {
      await stopMySession(activeSession.id)
      setActiveSession(null)
    } catch {}
    setStopping(false)
  }

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.container}>
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.greeting}>Welcome back</Text>
          <Text style={styles.shipName}>{profile?.ship_name ?? profile?.name ?? 'Sailor'}</Text>
        </View>

        <SessionStatusCard
          onStartPress={() => setShowModal(true)}
          onStopPress={handleStop}
          stopping={stopping}
        />

        <StartSessionModal
          visible={showModal}
          onClose={() => setShowModal(false)}
        />
      </ScrollView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#111827' },
  container: { padding: 20, gap: 20 },
  header: { marginBottom: 8 },
  greeting: { color: '#6b7280', fontSize: 14 },
  shipName: { color: '#fff', fontSize: 24, fontWeight: '800' },
})
