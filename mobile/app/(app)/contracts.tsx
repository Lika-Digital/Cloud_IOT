import { useState, useEffect, useCallback } from 'react'
import {
  View, Text, StyleSheet, SafeAreaView, ScrollView,
  TouchableOpacity, Alert, ActivityIndicator, Platform,
} from 'react-native'
import * as FileSystem from 'expo-file-system'
import * as Sharing from 'expo-sharing'
import {
  getPendingContracts, signContract, getMyContracts,
  type ContractTemplate, type CustomerContract,
} from '../../src/api/contracts'
import { SignaturePad } from '../../src/components/SignaturePad'
import { getToken } from '../../src/store/authStore'

const BASE_URL =
  Platform.OS === 'web' && typeof window !== 'undefined' && window.location.hostname === 'localhost'
    ? 'http://localhost:8000'
    : (process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000')

type Tab = 'pending' | 'signed'

export default function ContractsScreen() {
  const [activeTab, setActiveTab] = useState<Tab>('pending')
  const [pending, setPending] = useState<ContractTemplate[]>([])
  const [signed, setSigned] = useState<CustomerContract[]>([])
  const [loading, setLoading] = useState(true)
  const [signingId, setSigningId] = useState<number | null>(null)
  const [showSigPad, setShowSigPad] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [p, s] = await Promise.all([getPendingContracts(), getMyContracts()])
      setPending(p)
      setSigned(s)
    } catch {
      Alert.alert('Error', 'Failed to load contracts.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleSign = (templateId: number) => {
    setSigningId(templateId)
    setShowSigPad(true)
  }

  const handleSignConfirm = async (base64: string) => {
    setShowSigPad(false)
    if (!signingId) return
    try {
      await signContract(signingId, base64)
      Alert.alert('Signed!', 'Contract signed successfully.')
      setActiveTab('signed')
      load()
    } catch {
      Alert.alert('Error', 'Failed to sign contract. Please try again.')
    }
    setSigningId(null)
  }

  const handleDownloadPdf = async (contractId: number) => {
    const token = getToken()
    const url = `${BASE_URL}/api/customer/contracts/${contractId}/pdf`

    if (Platform.OS === 'web') {
      try {
        const resp = await fetch(url, { headers: { Authorization: `Bearer ${token}` } })
        const blob = await resp.blob()
        const objectUrl = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = objectUrl
        a.download = `contract_${contractId}.pdf`
        a.click()
        URL.revokeObjectURL(objectUrl)
      } catch {
        Alert.alert('Error', 'Failed to download PDF.')
      }
      return
    }

    const localPath = `${(FileSystem as any).documentDirectory}contract_${contractId}.pdf`
    try {
      const { uri } = await FileSystem.downloadAsync(url, localPath, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(uri, { mimeType: 'application/pdf' })
      } else {
        Alert.alert('Downloaded', `Saved to ${uri}`)
      }
    } catch {
      Alert.alert('Error', 'Failed to download PDF.')
    }
  }

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.header}>
        <Text style={styles.pageTitle}>Contracts</Text>
        <View style={styles.tabs}>
          {(['pending', 'signed'] as Tab[]).map((tab) => (
            <TouchableOpacity
              key={tab}
              style={[styles.tab, activeTab === tab && styles.tabActive]}
              onPress={() => setActiveTab(tab)}
            >
              <Text style={[styles.tabText, activeTab === tab && styles.tabTextActive]}>
                {tab === 'pending' ? `To Sign${pending.length ? ` (${pending.length})` : ''}` : 'My Contracts'}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color="#60a5fa" />
        </View>
      ) : activeTab === 'pending' ? (
        <ScrollView contentContainerStyle={styles.list}>
          {pending.length === 0 ? (
            <View style={styles.empty}>
              <Text style={styles.emptyIcon}>✅</Text>
              <Text style={styles.emptyText}>All contracts signed</Text>
            </View>
          ) : (
            pending.map((tpl) => (
              <View key={tpl.id} style={styles.card}>
                <Text style={styles.cardTitle}>{tpl.title}</Text>
                <Text style={styles.meta}>Valid for {tpl.validity_days} days</Text>
                <TouchableOpacity
                  style={styles.expandBtn}
                  onPress={() => setExpandedId(expandedId === tpl.id ? null : tpl.id)}
                >
                  <Text style={styles.expandBtnText}>
                    {expandedId === tpl.id ? 'Hide contract ▲' : 'Read contract ▼'}
                  </Text>
                </TouchableOpacity>
                {expandedId === tpl.id && (
                  <ScrollView style={styles.bodyScroll} nestedScrollEnabled>
                    <Text style={styles.bodyText}>{tpl.body}</Text>
                  </ScrollView>
                )}
                <TouchableOpacity
                  style={styles.signBtn}
                  onPress={() => handleSign(tpl.id)}
                >
                  <Text style={styles.signBtnText}>Sign with finger</Text>
                </TouchableOpacity>
              </View>
            ))
          )}
        </ScrollView>
      ) : (
        <ScrollView contentContainerStyle={styles.list}>
          {signed.length === 0 ? (
            <View style={styles.empty}>
              <Text style={styles.emptyIcon}>📝</Text>
              <Text style={styles.emptyText}>No signed contracts yet</Text>
            </View>
          ) : (
            signed.map((c) => (
              <View key={c.id} style={styles.card}>
                <Text style={styles.cardTitle}>{c.template_title ?? `Contract #${c.id}`}</Text>
                <Text style={styles.meta}>
                  Signed {new Date(c.signed_at).toLocaleDateString()}
                  {c.valid_until ? ` · Valid until ${new Date(c.valid_until).toLocaleDateString()}` : ''}
                </Text>
                <View style={styles.row}>
                  <View style={[
                    styles.badge,
                    c.status === 'active' ? styles.badgeGreen : styles.badgeGray,
                  ]}>
                    <Text style={styles.badgeText}>{c.status}</Text>
                  </View>
                  <TouchableOpacity style={styles.pdfBtn} onPress={() => handleDownloadPdf(c.id)}>
                    <Text style={styles.pdfBtnText}>View PDF</Text>
                  </TouchableOpacity>
                </View>
              </View>
            ))
          )}
        </ScrollView>
      )}

      <SignaturePad
        visible={showSigPad}
        onConfirm={handleSignConfirm}
        onCancel={() => { setShowSigPad(false); setSigningId(null) }}
      />
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#111827' },
  header: { padding: 20, paddingBottom: 0 },
  pageTitle: { color: '#fff', fontSize: 24, fontWeight: '800', marginBottom: 16 },
  tabs: { flexDirection: 'row', gap: 8, marginBottom: 16 },
  tab: {
    flex: 1,
    paddingVertical: 8,
    borderRadius: 10,
    backgroundColor: '#1f2937',
    alignItems: 'center',
  },
  tabActive: { backgroundColor: '#2563eb' },
  tabText: { color: '#6b7280', fontWeight: '600', fontSize: 13 },
  tabTextActive: { color: '#fff' },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  list: { padding: 20, gap: 16 },
  empty: { alignItems: 'center', paddingTop: 60, gap: 12 },
  emptyIcon: { fontSize: 48 },
  emptyText: { color: '#6b7280', fontSize: 16 },
  card: {
    backgroundColor: '#1f2937',
    borderRadius: 16,
    padding: 16,
    gap: 10,
  },
  cardTitle: { color: '#f9fafb', fontSize: 16, fontWeight: '700' },
  meta: { color: '#6b7280', fontSize: 12 },
  expandBtn: { alignSelf: 'flex-start' },
  expandBtnText: { color: '#60a5fa', fontSize: 13, fontWeight: '600' },
  bodyScroll: {
    maxHeight: 200,
    backgroundColor: '#111827',
    borderRadius: 8,
    padding: 10,
  },
  bodyText: { color: '#d1d5db', fontSize: 12, lineHeight: 18 },
  signBtn: {
    backgroundColor: '#2563eb',
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
  },
  signBtnText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  badge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 20 },
  badgeGreen: { backgroundColor: '#14532d' },
  badgeGray: { backgroundColor: '#374151' },
  badgeText: { color: '#86efac', fontSize: 12, fontWeight: '600' },
  pdfBtn: {
    backgroundColor: '#1e3a5f',
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 8,
  },
  pdfBtnText: { color: '#60a5fa', fontWeight: '600', fontSize: 13 },
})
