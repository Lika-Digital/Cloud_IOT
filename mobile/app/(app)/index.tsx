import { useState, useEffect, useCallback } from 'react'
import {
  View, Text, StyleSheet, SafeAreaView, ScrollView,
  TouchableOpacity, Linking, ActivityIndicator, Alert, Image,
} from 'react-native'
import { useRouter } from 'expo-router'
import { useAuthStore } from '../../src/store/authStore'
import { useSessionStore } from '../../src/store/sessionStore'
import { useTheme } from '../../src/hooks/useTheme'
import { useThemeStore } from '../../src/store/themeStore'
import { getMySessions } from '../../src/api/sessions'
import { SessionStatusCard } from '../../src/components/SessionStatusCard'
import { StartSessionModal } from '../../src/components/StartSessionModal'
import { stopMySession } from '../../src/api/sessions'
import { getPendingContracts, getMyContracts, type CustomerContract } from '../../src/api/contracts'
import { ShipCameraModal } from '../../src/components/ShipCameraModal'
import { BerthBookingModal } from '../../src/components/BerthBookingModal'
import { type ReservationOut } from '../../src/api/berths'

export default function HomeScreen() {
  const { profile } = useAuthStore()
  const { setActiveSession, activeSession } = useSessionStore()
  const router = useRouter()
  const t = useTheme()
  const { mode, setMode } = useThemeStore()
  const [showModal, setShowModal] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [showCamera, setShowCamera] = useState(false)
  const [showBerthModal, setShowBerthModal] = useState(false)

  const [pendingCount, setPendingCount] = useState(0)
  const [signedContract, setSignedContract] = useState<CustomerContract | null>(null)
  const [contractsLoaded, setContractsLoaded] = useState(false)

  useEffect(() => {
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
    } catch {
      Alert.alert('Error', 'Failed to stop session. Please try again.')
    } finally {
      setStopping(false)
    }
  }

  const openMap = () => {
    Linking.openURL('https://maps.apple.com/?q=Marina+Portoro%C5%BE&ll=45.5133,13.5919').catch(() => {
      Linking.openURL('https://www.google.com/maps?q=Marina+Portoroz+Slovenia')
    })
  }

  const cycleTheme = () => {
    const next: Record<string, 'light' | 'dark' | 'system'> = {
      system: 'dark',
      dark: 'light',
      light: 'system',
    }
    setMode(next[mode])
  }

  const themeIcon = mode === 'dark' ? '🌙' : mode === 'light' ? '☀️' : '⚙️'

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: t.bg }]}>
      <ScrollView
        contentContainerStyle={[styles.container]}
        showsVerticalScrollIndicator={false}
      >
        {/* ── Header ─────────────────────────────────────────── */}
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <Image
              source={require('../../assets/logo.png')}
              style={styles.logo}
              resizeMode="contain"
            />
            <View>
              <Text style={[styles.greeting, { color: t.textMuted }]}>Welcome back</Text>
              <Text style={[styles.shipName, { color: t.textPrimary }]}>
                {profile?.ship_name ?? profile?.name ?? 'Sailor'}
              </Text>
            </View>
          </View>
          <TouchableOpacity
            style={[styles.themeToggle, { backgroundColor: t.card, borderColor: t.border }]}
            onPress={cycleTheme}
            accessibilityLabel="Toggle theme"
          >
            <Text style={styles.themeIcon}>{themeIcon}</Text>
          </TouchableOpacity>
        </View>

        {/* ── 1. Marina info card (first) ─────────────────────── */}
        <View style={[styles.marinaCard, { backgroundColor: t.marinaCard, borderColor: t.border }]}>
          <View style={styles.marinaHeader}>
            <Text style={styles.marinaFlag}>⚓</Text>
            <View style={styles.marinaHeaderText}>
              <Text style={[styles.marinaName, { color: '#fff' }]}>Marina Portorož</Text>
              <Text style={[styles.marinaTagline, { color: '#93c5fd' }]}>Slovenia's Premier Marina</Text>
            </View>
          </View>
          <View style={[styles.marinaDivider, { backgroundColor: t.isDark ? '#2563eb30' : '#3b82f620' }]} />
          <Text style={[styles.marinaInfo, { color: '#93c5fd' }]}>📍 Cesta solinarjev 8, 6320 Portorož, Slovenia</Text>
          <Text style={[styles.marinaInfo, { color: '#93c5fd' }]}>📞 +386 5 676 02 00</Text>
          <View style={styles.chipsRow}>
            {['⚡ 4 Sockets', '💧 Water', '📶 Wi-Fi', '🏗️ Crane', '🚢 600 Berths'].map((s) => (
              <View key={s} style={[styles.chip, { backgroundColor: t.isDark ? '#1d4ed840' : '#dbeafe' }]}>
                <Text style={[styles.chipText, { color: t.isDark ? '#93c5fd' : '#1e40af' }]}>{s}</Text>
              </View>
            ))}
          </View>
          <TouchableOpacity style={[styles.mapBtn, { backgroundColor: t.accent }]} onPress={openMap}>
            <Text style={styles.mapBtnText}>Open in Maps →</Text>
          </TouchableOpacity>
        </View>

        {/* ── 2. Session card ─────────────────────────────────── */}
        <SessionStatusCard
          onStartPress={() => setShowModal(true)}
          onStopPress={handleStop}
          stopping={stopping}
        />

        {/* ── 3. Quick actions row ────────────────────────────── */}
        <View style={styles.quickRow}>
          <TouchableOpacity
            style={[styles.quickCard, { backgroundColor: t.card, borderColor: t.border }]}
            onPress={() => setShowCamera(true)}
            activeOpacity={0.85}
          >
            <Text style={styles.quickIcon}>📷</Text>
            <Text style={[styles.quickTitle, { color: t.textPrimary }]}>My Ship</Text>
            <View style={styles.livePill}>
              <View style={styles.liveDot} />
              <Text style={styles.liveText}>LIVE</Text>
            </View>
          </TouchableOpacity>

          <TouchableOpacity
            style={[styles.quickCard, { backgroundColor: t.card, borderColor: t.border }]}
            onPress={() => setShowBerthModal(true)}
            activeOpacity={0.85}
          >
            <Text style={styles.quickIcon}>⚓</Text>
            <Text style={[styles.quickTitle, { color: t.textPrimary }]}>Book Berth</Text>
            <Text style={[styles.quickSub, { color: t.textMuted }]}>Reserve →</Text>
          </TouchableOpacity>
        </View>

        {/* ── 4. Contracts banner ─────────────────────────────── */}
        {contractsLoaded ? (
          <TouchableOpacity
            style={[
              styles.contractBanner,
              pendingCount > 0
                ? { backgroundColor: '#78350f', borderColor: '#d97706', borderWidth: 1 }
                : { backgroundColor: '#14532d', borderColor: '#16a34a', borderWidth: 1 },
            ]}
            onPress={() => router.push('/(app)/contracts')}
          >
            <View style={styles.contractRow}>
              <Text style={styles.contractIcon}>{pendingCount > 0 ? '⚠️' : '✅'}</Text>
              <View style={{ flex: 1 }}>
                {pendingCount > 0 ? (
                  <>
                    <Text style={styles.contractTitle}>Sign your marina contract</Text>
                    <Text style={styles.contractSub}>
                      {pendingCount} contract{pendingCount > 1 ? 's' : ''} awaiting signature
                    </Text>
                  </>
                ) : signedContract ? (
                  <>
                    <Text style={styles.contractTitle}>{signedContract.template_title ?? 'Contract'}</Text>
                    <Text style={styles.contractSub}>
                      Valid until{' '}
                      {signedContract.valid_until
                        ? new Date(signedContract.valid_until).toLocaleDateString()
                        : '—'}
                    </Text>
                  </>
                ) : (
                  <>
                    <Text style={styles.contractTitle}>No contracts</Text>
                    <Text style={styles.contractSub}>Tap to view available contracts</Text>
                  </>
                )}
              </View>
              <Text style={{ color: '#d1d5db', fontSize: 22 }}>›</Text>
            </View>
          </TouchableOpacity>
        ) : (
          <View style={[styles.loadingCard, { backgroundColor: t.card }]}>
            <ActivityIndicator size="small" color={t.accentLight} />
          </View>
        )}

        {/* ── 5. Marina services grid ─────────────────────────── */}
        <View style={[styles.servicesCard, { backgroundColor: t.card, borderColor: t.border }]}>
          <View style={styles.servicesHeader}>
            <Text style={[styles.servicesTitle, { color: t.textPrimary }]}>Marina Services</Text>
            <TouchableOpacity
              style={[styles.helpBtnSmall, { backgroundColor: t.accentBg }]}
              onPress={() => Alert.alert(
                'Marina Services',
                'Tap any service to submit a request to our marina team.\n\nServices include crane operations, engine checks, hull cleaning, diver assistance, battery charging, and electrical work.\n\nYour request will be reviewed and a team member will contact you.',
              )}
            >
              <Text style={[styles.helpBtnSmallText, { color: t.accentLight }]}>?</Text>
            </TouchableOpacity>
          </View>
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
                style={[styles.serviceItem, { backgroundColor: t.bgSecondary, borderColor: t.border }]}
                onPress={() => router.push('/(app)/services')}
              >
                <Text style={styles.serviceIcon}>{s.icon}</Text>
                <Text style={[styles.serviceLabel, { color: t.textSecondary }]}>{s.label}</Text>
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
          Alert.alert('⚓ Berth Reserved!', `${res.berth_name}\n${res.check_in_date} → ${res.check_out_date}`)
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
  safe: { flex: 1 },
  container: { padding: 20, gap: 16, paddingBottom: 40 },

  // Header
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  logo: { width: 40, height: 40, borderRadius: 8 },
  greeting: { fontSize: 12 },
  shipName: { fontSize: 22, fontWeight: '800' },
  themeToggle: {
    width: 40, height: 40, borderRadius: 20,
    alignItems: 'center', justifyContent: 'center',
    borderWidth: 1,
  },
  themeIcon: { fontSize: 18 },

  // Marina card
  marinaCard: {
    borderRadius: 20,
    padding: 18,
    gap: 10,
    borderWidth: 1,
  },
  marinaHeader: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  marinaFlag: { fontSize: 32 },
  marinaHeaderText: { flex: 1 },
  marinaName: { fontSize: 18, fontWeight: '800' },
  marinaTagline: { fontSize: 12 },
  marinaDivider: { height: 1 },
  marinaInfo: { fontSize: 13 },
  chipsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 20 },
  chipText: { fontSize: 11 },
  mapBtn: { borderRadius: 10, paddingVertical: 10, alignItems: 'center' },
  mapBtnText: { color: '#fff', fontWeight: '700', fontSize: 13 },

  // Quick actions
  quickRow: { flexDirection: 'row', gap: 12 },
  quickCard: {
    flex: 1,
    borderRadius: 16,
    padding: 16,
    alignItems: 'center',
    gap: 8,
    borderWidth: 1,
  },
  quickIcon: { fontSize: 30 },
  quickTitle: { fontWeight: '700', fontSize: 14 },
  quickSub: { fontSize: 12 },
  livePill: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    backgroundColor: '#dc2626', paddingHorizontal: 8,
    paddingVertical: 3, borderRadius: 12,
  },
  liveDot: { width: 5, height: 5, borderRadius: 2.5, backgroundColor: '#fff' },
  liveText: { color: '#fff', fontWeight: '800', fontSize: 10 },

  // Contract banner
  contractBanner: { borderRadius: 16, padding: 14 },
  contractRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  contractIcon: { fontSize: 26 },
  contractTitle: { color: '#fff', fontSize: 14, fontWeight: '700' },
  contractSub: { color: '#d1d5db', fontSize: 12, marginTop: 2 },

  loadingCard: { borderRadius: 16, padding: 24, alignItems: 'center' },

  // Services
  servicesCard: { borderRadius: 20, padding: 18, gap: 14, borderWidth: 1 },
  servicesHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  servicesTitle: { fontSize: 16, fontWeight: '700' },
  helpBtnSmall: {
    width: 24, height: 24, borderRadius: 12,
    alignItems: 'center', justifyContent: 'center',
  },
  helpBtnSmallText: { fontSize: 13, fontWeight: '800' },
  servicesGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  serviceItem: {
    width: '30%',
    borderRadius: 14,
    padding: 12,
    alignItems: 'center',
    gap: 5,
    borderWidth: 1,
  },
  serviceIcon: { fontSize: 26 },
  serviceLabel: { fontSize: 11, fontWeight: '600', textAlign: 'center' },
})
