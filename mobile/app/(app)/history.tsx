import { useState, useEffect, useCallback } from 'react'
import {
  View, Text, StyleSheet, SafeAreaView,
  ScrollView, TouchableOpacity, ActivityIndicator, Alert,
} from 'react-native'
import { getMySessions, type Session } from '../../src/api/sessions'
import { getMyInvoices, payInvoice, type Invoice } from '../../src/api/invoices'
import { getMyReviews, type Review } from '../../src/api/reviews'
import { InvoiceCard } from '../../src/components/InvoiceCard'
import { ReviewModal } from '../../src/components/ReviewModal'

type Tab = 'sessions' | 'invoices'

export default function HistoryScreen() {
  const [tab, setTab] = useState<Tab>('sessions')
  const [sessions, setSessions] = useState<Session[]>([])
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [myReviews, setMyReviews] = useState<Review[]>([])
  const [loading, setLoading] = useState(true)
  const [reviewTarget, setReviewTarget] = useState<{ sessionId: number; title: string } | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [s, i, r] = await Promise.all([getMySessions(), getMyInvoices(), getMyReviews()])
      setSessions(s)
      setInvoices(i)
      setMyReviews(r)
    } catch {}
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [])

  const handleInvoicePaid = (updated: Invoice) =>
    setInvoices((prev) => prev.map((inv) => (inv.id === updated.id ? updated : inv)))

  return (
    <SafeAreaView style={styles.safe}>
      {/* ── Screen header ─────────────────────────────────────── */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>History</Text>
        <Text style={styles.headerSub}>Your sessions &amp; invoices</Text>
      </View>

      {/* ── Tab bar ───────────────────────────────────────────── */}
      <View style={styles.tabBar}>
        {(['sessions', 'invoices'] as Tab[]).map((t) => (
          <TouchableOpacity
            key={t}
            style={[styles.tab, tab === t && styles.tabActive]}
            onPress={() => setTab(t)}
            activeOpacity={0.8}
          >
            <Text style={styles.tabIcon}>{t === 'sessions' ? '📋' : '🧾'}</Text>
            <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>
              {t === 'sessions' ? 'Sessions' : 'Invoices'}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {loading ? (
        <ActivityIndicator style={{ marginTop: 60 }} color="#60a5fa" size="large" />
      ) : (
        <ScrollView contentContainerStyle={styles.list}>
          {tab === 'sessions' && (
            sessions.length === 0
              ? <EmptyState icon="📋" text="No sessions yet." />
              : sessions.map((s) => (
                  <SessionRow
                    key={s.id}
                    session={s}
                    alreadyReviewed={myReviews.some((r) => r.session_id === s.id)}
                    onReview={() => setReviewTarget({
                      sessionId: s.id,
                      title: `${s.type === 'electricity' ? '⚡ Electricity' : '💧 Water'} Session`,
                    })}
                  />
                ))
          )}
          {tab === 'invoices' && (
            invoices.length === 0
              ? <EmptyState icon="🧾" text="No invoices yet." />
              : invoices.map((inv) => (
                  <InvoiceCard key={inv.id} invoice={inv} onPaid={handleInvoicePaid} />
                ))
          )}
        </ScrollView>
      )}

      <ReviewModal
        visible={reviewTarget !== null}
        sessionId={reviewTarget?.sessionId}
        title={reviewTarget?.title}
        onClose={() => setReviewTarget(null)}
        onSubmitted={() => {
          setReviewTarget(null)
          Alert.alert('Thank you!', 'Your review has been submitted.')
          load()
        }}
      />
    </SafeAreaView>
  )
}

// ─── Session row ─────────────────────────────────────────────────────────────
function SessionRow({
  session,
  alreadyReviewed,
  onReview,
}: {
  session: Session
  alreadyReviewed: boolean
  onReview: () => void
}) {
  const statusMeta: Record<string, { color: string; label: string; icon: string }> = {
    completed: { color: '#4ade80', label: 'Completed', icon: '✅' },
    denied:    { color: '#f87171', label: 'Denied',    icon: '❌' },
    pending:   { color: '#fbbf24', label: 'Pending',   icon: '⏳' },
    active:    { color: '#60a5fa', label: 'Active',    icon: '🔵' },
  }
  const meta = statusMeta[session.status] ?? { color: '#9ca3af', label: session.status, icon: '•' }

  const isElec = session.type === 'electricity'
  const date = new Date(session.started_at)
  const dateStr = date.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })
  const timeStr = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

  return (
    <View style={rowStyles.card}>
      {/* Left accent bar */}
      <View style={[rowStyles.accent, { backgroundColor: meta.color }]} />

      <View style={rowStyles.body}>
        {/* Top row */}
        <View style={rowStyles.topRow}>
          <View style={rowStyles.typeTag}>
            <Text style={rowStyles.typeIcon}>{isElec ? '⚡' : '💧'}</Text>
            <Text style={rowStyles.typeText}>{isElec ? 'Electricity' : 'Water'}</Text>
            {isElec && session.socket_id != null && (
              <Text style={rowStyles.socketBadge}>Socket {session.socket_id}</Text>
            )}
          </View>
          <View style={rowStyles.statusBadge}>
            <Text style={rowStyles.statusIcon}>{meta.icon}</Text>
            <Text style={[rowStyles.statusText, { color: meta.color }]}>{meta.label}</Text>
          </View>
        </View>

        {/* Date / time */}
        <Text style={rowStyles.date}>{dateStr}  {timeStr}</Text>

        {/* Usage */}
        {(session.energy_kwh != null || session.water_liters != null) && (
          <View style={rowStyles.usageRow}>
            {session.energy_kwh != null && (
              <Text style={rowStyles.usage}>⚡ {session.energy_kwh.toFixed(4)} kWh</Text>
            )}
            {session.water_liters != null && (
              <Text style={rowStyles.usage}>💧 {session.water_liters.toFixed(2)} L</Text>
            )}
          </View>
        )}

        {/* Denial reason */}
        {session.deny_reason && (
          <Text style={rowStyles.reason}>Reason: {session.deny_reason}</Text>
        )}

        {/* Rate button — only for completed sessions */}
        {session.status === 'completed' && (
          alreadyReviewed
            ? <Text style={rowStyles.reviewed}>★ Reviewed</Text>
            : (
              <TouchableOpacity style={rowStyles.rateBtn} onPress={onReview}>
                <Text style={rowStyles.rateBtnText}>★ Rate this session</Text>
              </TouchableOpacity>
            )
        )}
      </View>
    </View>
  )
}

function EmptyState({ icon, text }: { icon: string; text: string }) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyIcon}>{icon}</Text>
      <Text style={styles.emptyText}>{text}</Text>
    </View>
  )
}

// ─── Styles ──────────────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#111827' },

  header: {
    paddingTop: 20,
    paddingHorizontal: 20,
    paddingBottom: 8,
  },
  headerTitle: { color: '#f9fafb', fontSize: 28, fontWeight: '800' },
  headerSub:   { color: '#6b7280', fontSize: 14, marginTop: 2 },

  tabBar: {
    flexDirection: 'row',
    marginHorizontal: 20,
    marginTop: 16,
    marginBottom: 4,
    gap: 10,
  },
  tab: {
    flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: 6, paddingVertical: 11, borderRadius: 12,
    backgroundColor: '#1f2937', borderWidth: 1, borderColor: '#374151',
  },
  tabActive: { backgroundColor: '#1e3a5f', borderColor: '#3b82f6' },
  tabIcon:   { fontSize: 16 },
  tabText:       { color: '#6b7280', fontWeight: '600', fontSize: 14 },
  tabTextActive: { color: '#60a5fa' },

  list: { padding: 16, paddingTop: 12, gap: 10 },

  empty: { alignItems: 'center', marginTop: 60, gap: 12 },
  emptyIcon: { fontSize: 48 },
  emptyText: { color: '#6b7280', fontSize: 16 },
})

const rowStyles = StyleSheet.create({
  card: {
    backgroundColor: '#1f2937',
    borderRadius: 14,
    flexDirection: 'row',
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: '#374151',
  },
  accent: { width: 4 },
  body: { flex: 1, padding: 14, gap: 5 },

  topRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  typeTag: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  typeIcon: { fontSize: 14 },
  typeText: { color: '#e5e7eb', fontWeight: '700', fontSize: 14 },
  socketBadge: {
    backgroundColor: '#374151', borderRadius: 6,
    paddingHorizontal: 7, paddingVertical: 2,
    color: '#9ca3af', fontSize: 11, fontWeight: '600',
  },

  statusBadge: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  statusIcon: { fontSize: 12 },
  statusText: { fontWeight: '700', fontSize: 13 },

  date: { color: '#6b7280', fontSize: 12 },

  usageRow: { flexDirection: 'row', gap: 16, marginTop: 2 },
  usage: { color: '#9ca3af', fontSize: 12, fontFamily: 'monospace' },

  reason: { color: '#f87171', fontSize: 12, marginTop: 2 },

  rateBtn: {
    marginTop: 6,
    alignSelf: 'flex-start',
    backgroundColor: '#1e3a5f',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderWidth: 1,
    borderColor: '#3b82f6',
  },
  rateBtnText: { color: '#60a5fa', fontWeight: '700', fontSize: 12 },
  reviewed: { color: '#fbbf24', fontSize: 12, marginTop: 6, fontWeight: '600' },
})
