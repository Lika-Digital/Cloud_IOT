import { useState, useEffect, useCallback } from 'react'
import {
  View, Text, StyleSheet, SafeAreaView, ScrollView,
  TouchableOpacity, Linking, ActivityIndicator, Alert,
} from 'react-native'
import { useRouter } from 'expo-router'
import { useAuthStore } from '../../src/store/authStore'
import { useSessionStore } from '../../src/store/sessionStore'
import { getMySessions } from '../../src/api/sessions'
import { SessionStatusCard } from '../../src/components/SessionStatusCard'
import { StartSessionModal } from '../../src/components/StartSessionModal'
import { useWebSocket } from '../../src/hooks/useWebSocket'
import { stopMySession } from '../../src/api/sessions'
import { getPendingContracts, getMyContracts, type CustomerContract } from '../../src/api/contracts'
import { ShipCameraModal } from '../../src/components/ShipCameraModal'
import { BerthBookingModal } from '../../src/components/BerthBookingModal'
import { type ReservationOut } from '../../src/api/berths'

export default function HomeScreen() {
  const { profile } = useAuthStore()
  const { setActiveSession, activeSession } = useSessionStore()
  const router = useRouter()
  const [showModal, setShowModal] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [showCamera, setShowCamera] = useState(false)
  const [showBerthModal, setShowBerthModal] = useState(false)

  // Contract state
  const [pendingCount, setPendingCount] = useState(0)
  const [signedContract, setSignedContract] = useState<CustomerContract | null>(null)
  const [contractsLoaded, setContractsLoaded] = useState(false)

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

  const loadContracts = useCallback(() => {
    Promise.all([getPendingContracts(), getMyContracts()])
      .then(([pending, mine]) => {
        setPendingCount(pending.length)
        setSignedContract(mine[0] ?? null)
        setContractsLoaded(true)
      })
      .catch(() => setContractsLoaded(true))
  }, [])

  useEffect(() => { loadContracts() }, [loadContracts])

  const handleStop = async () => {
    if (!activeSession) return
    setStopping(true)
    try {
      await stopMySession(activeSession.id)
      setActiveSession(null)
    } catch {}
    setStopping(false)
  }

  const openMap = () => {
    const url = 'https://maps.apple.com/?q=Marina+Portoro%C5%BE&ll=45.5133,13.5919'
    Linking.openURL(url).catch(() => {
      Linking.openURL('https://www.google.com/maps?q=Marina+Portoroz+Slovenia')
    })
  }

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.container}>
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.greeting}>Welcome back</Text>
          <Text style={styles.shipName}>{profile?.ship_name ?? profile?.name ?? 'Sailor'}</Text>
        </View>

        {/* 1. Session card */}
        <SessionStatusCard
          onStartPress={() => setShowModal(true)}
          onStopPress={handleStop}
          stopping={stopping}
        />

        {/* 2. Marina info card */}
        <View style={styles.marinaCard}>
          <View style={styles.marinaHeader}>
            <Text style={styles.marinaFlag}>⚓</Text>
            <View style={styles.marinaHeaderText}>
              <Text style={styles.marinaName}>Marina Portorož</Text>
              <Text style={styles.marinaTagline}>Slovenia's Premier Marina</Text>
            </View>
          </View>
          <View style={styles.marinaDivider} />
          <Text style={styles.marinaAddress}>📍 Cesta solinarjev 8, 6320 Portorož, Slovenia</Text>
          <Text style={styles.marinaPhone}>📞 +386 5 676 02 00</Text>
          <View style={styles.servicesRow}>
            {['⚡ 4 Sockets', '💧 Water', '📶 Wi-Fi', '🏗️ Crane', '🚢 600 Berths'].map((s) => (
              <View key={s} style={styles.serviceChip}>
                <Text style={styles.serviceChipText}>{s}</Text>
              </View>
            ))}
          </View>
          <TouchableOpacity style={styles.mapBtn} onPress={openMap}>
            <Text style={styles.mapBtnText}>Open in Maps →</Text>
          </TouchableOpacity>
        </View>

        {/* 3. Check My Ship */}
        <TouchableOpacity style={styles.cameraCard} onPress={() => setShowCamera(true)} activeOpacity={0.85}>
          <View style={styles.cameraCardLeft}>
            <Text style={styles.cameraIcon}>📷</Text>
            <View>
              <Text style={styles.cameraTitle}>Check My Ship</Text>
              <Text style={styles.cameraSub}>Live berth camera view</Text>
            </View>
          </View>
          <View style={styles.livePill}>
            <View style={styles.liveDot} />
            <Text style={styles.liveText}>LIVE</Text>
          </View>
        </TouchableOpacity>

        {/* 4. Book a Berth card */}
        <TouchableOpacity style={styles.berthCard} onPress={() => setShowBerthModal(true)} activeOpacity={0.85}>
          <View style={styles.berthCardLeft}>
            <Text style={styles.berthIcon}>⚓</Text>
            <View>
              <Text style={styles.berthTitle}>Book a Berth</Text>
              <Text style={styles.berthSub}>Check availability & reserve</Text>
            </View>
          </View>
          <Text style={styles.berthArrow}>›</Text>
        </TouchableOpacity>

        {/* 5. Contracts banner */}
        {contractsLoaded ? (
          <TouchableOpacity
            style={[
              styles.contractBanner,
              pendingCount > 0 ? styles.contractBannerAmber : styles.contractBannerGreen,
            ]}
            onPress={() => router.push('/(app)/contracts')}
          >
            <View style={styles.contractBannerContent}>
              <Text style={styles.contractIcon}>{pendingCount > 0 ? '⚠️' : '✅'}</Text>
              <View style={styles.contractBannerText}>
                {pendingCount > 0 ? (
                  <>
                    <Text style={styles.contractBannerTitle}>Sign your marina contract</Text>
                    <Text style={styles.contractBannerSub}>
                      {pendingCount} contract{pendingCount > 1 ? 's' : ''} awaiting signature
                    </Text>
                  </>
                ) : signedContract ? (
                  <>
                    <Text style={styles.contractBannerTitle}>{signedContract.template_title ?? 'Contract'}</Text>
                    <Text style={styles.contractBannerSub}>
                      Valid until{' '}
                      {signedContract.valid_until
                        ? new Date(signedContract.valid_until).toLocaleDateString()
                        : '—'}
                    </Text>
                  </>
                ) : (
                  <>
                    <Text style={styles.contractBannerTitle}>No contracts</Text>
                    <Text style={styles.contractBannerSub}>Tap to view available contracts</Text>
                  </>
                )}
              </View>
              <Text style={styles.contractArrow}>›</Text>
            </View>
          </TouchableOpacity>
        ) : (
          <View style={styles.contractBannerLoading}>
            <ActivityIndicator size="small" color="#60a5fa" />
          </View>
        )}

        {/* 4. Marina services grid */}
        <View style={styles.servicesCard}>
          <Text style={styles.servicesCardTitle}>Marina Services</Text>
          <View style={styles.servicesGrid}>
            {[
              { icon: '🏗️', label: 'Crane' },
              { icon: '⚙️', label: 'Engine Check' },
              { icon: '🚢', label: 'Hull Clean' },
              { icon: '🤿', label: 'Diver' },
              { icon: '🔋', label: 'Battery' },
              { icon: '⚡', label: 'Electrical' },
            ].map((s) => (
              <TouchableOpacity
                key={s.label}
                style={styles.serviceGridItem}
                onPress={() => router.push('/(app)/services')}
              >
                <Text style={styles.serviceGridIcon}>{s.icon}</Text>
                <Text style={styles.serviceGridLabel}>{s.label}</Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>
      </ScrollView>

      <StartSessionModal visible={showModal} onClose={() => setShowModal(false)} />
      <BerthBookingModal
        visible={showBerthModal}
        onClose={() => setShowBerthModal(false)}
        onReserved={(res: ReservationOut) => {
          setShowBerthModal(false)
          Alert.alert(
            '⚓ Berth Reserved!',
            `${res.berth_name}\n${res.check_in_date} → ${res.check_out_date}`,
            [{ text: 'OK' }],
          )
        }}
      />
      <ShipCameraModal
        visible={showCamera}
        shipName={profile?.ship_name ?? undefined}
        onClose={() => setShowCamera(false)}
      />
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#111827' },
  container: { padding: 20, gap: 20, paddingBottom: 40 },
  header: { marginBottom: 4 },
  greeting: { color: '#6b7280', fontSize: 14 },
  shipName: { color: '#fff', fontSize: 24, fontWeight: '800' },

  // Marina card
  marinaCard: {
    backgroundColor: '#1e3a5f',
    borderRadius: 20,
    padding: 18,
    gap: 10,
    borderWidth: 1,
    borderColor: '#2563eb40',
  },
  marinaHeader: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  marinaFlag: { fontSize: 32 },
  marinaHeaderText: { flex: 1 },
  marinaName: { color: '#fff', fontSize: 18, fontWeight: '800' },
  marinaTagline: { color: '#93c5fd', fontSize: 12 },
  marinaDivider: { height: 1, backgroundColor: '#2563eb30' },
  marinaAddress: { color: '#93c5fd', fontSize: 13 },
  marinaPhone: { color: '#93c5fd', fontSize: 13 },
  servicesRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  serviceChip: {
    backgroundColor: '#1d4ed840',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 20,
  },
  serviceChipText: { color: '#93c5fd', fontSize: 11 },
  mapBtn: {
    backgroundColor: '#2563eb',
    borderRadius: 10,
    paddingVertical: 10,
    alignItems: 'center',
  },
  mapBtnText: { color: '#fff', fontWeight: '700', fontSize: 13 },

  // Berth booking card
  berthCard: {
    backgroundColor: '#0f172a',
    borderRadius: 16,
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderWidth: 1,
    borderColor: '#1e3a5f',
  },
  berthCardLeft: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  berthIcon: { fontSize: 32 },
  berthTitle: { color: '#f9fafb', fontWeight: '700', fontSize: 15 },
  berthSub: { color: '#6b7280', fontSize: 12, marginTop: 2 },
  berthArrow: { color: '#60a5fa', fontSize: 26 },

  // Camera card
  cameraCard: {
    backgroundColor: '#0f172a',
    borderRadius: 16,
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderWidth: 1,
    borderColor: '#1e3a5f',
  },
  cameraCardLeft: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  cameraIcon: { fontSize: 32 },
  cameraTitle: { color: '#f9fafb', fontWeight: '700', fontSize: 15 },
  cameraSub: { color: '#6b7280', fontSize: 12, marginTop: 2 },
  livePill: {
    flexDirection: 'row', alignItems: 'center', gap: 5,
    backgroundColor: '#dc2626', paddingHorizontal: 10,
    paddingVertical: 5, borderRadius: 20,
  },
  liveDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: '#fff' },
  liveText: { color: '#fff', fontWeight: '800', fontSize: 11 },

  // Contract banner
  contractBanner: {
    borderRadius: 16,
    padding: 16,
  },
  contractBannerAmber: { backgroundColor: '#78350f', borderWidth: 1, borderColor: '#d97706' },
  contractBannerGreen: { backgroundColor: '#14532d', borderWidth: 1, borderColor: '#16a34a' },
  contractBannerLoading: {
    backgroundColor: '#1f2937',
    borderRadius: 16,
    padding: 24,
    alignItems: 'center',
  },
  contractBannerContent: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  contractIcon: { fontSize: 28 },
  contractBannerText: { flex: 1 },
  contractBannerTitle: { color: '#fff', fontSize: 15, fontWeight: '700' },
  contractBannerSub: { color: '#d1d5db', fontSize: 12, marginTop: 2 },
  contractArrow: { color: '#d1d5db', fontSize: 22 },

  // Services card
  servicesCard: {
    backgroundColor: '#1f2937',
    borderRadius: 20,
    padding: 18,
    gap: 14,
  },
  servicesCardTitle: { color: '#f9fafb', fontSize: 16, fontWeight: '700' },
  servicesGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  serviceGridItem: {
    width: '30%',
    backgroundColor: '#111827',
    borderRadius: 14,
    padding: 14,
    alignItems: 'center',
    gap: 6,
  },
  serviceGridIcon: { fontSize: 28 },
  serviceGridLabel: { color: '#d1d5db', fontSize: 11, fontWeight: '600', textAlign: 'center' },
})
