import { useState } from 'react'
import {
  Modal, View, Text, TextInput, TouchableOpacity,
  StyleSheet, ScrollView, ActivityIndicator, Alert,
} from 'react-native'
import { getAvailableBerths, reserveBerth, type BerthOut, type ReservationOut } from '../api/berths'

interface Props {
  visible: boolean
  onClose: () => void
  onReserved: (reservation: ReservationOut) => void
}

type Step = 'dates' | 'availability' | 'confirmation'

const TODAY = new Date().toISOString().slice(0, 10)
const TOMORROW = new Date(Date.now() + 86400000).toISOString().slice(0, 10)

function validateDate(s: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(s) && !isNaN(Date.parse(s))
}

export function BerthBookingModal({ visible, onClose, onReserved }: Props) {
  const [step, setStep] = useState<Step>('dates')
  const [checkIn, setCheckIn] = useState(TODAY)
  const [checkOut, setCheckOut] = useState(TOMORROW)
  const [notes, setNotes] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [berths, setBerths] = useState<BerthOut[]>([])
  const [selected, setSelected] = useState<BerthOut | null>(null)
  const [confirming, setConfirming] = useState(false)

  const reset = () => {
    setStep('dates')
    setCheckIn(TODAY)
    setCheckOut(TOMORROW)
    setNotes('')
    setError('')
    setBerths([])
    setSelected(null)
  }

  const handleClose = () => { reset(); onClose() }

  // ── Step 1: validate dates → fetch availability ──────────────────────────
  const handleCheckAvailability = async () => {
    setError('')
    if (!validateDate(checkIn)) { setError('Invalid check-in date (use YYYY-MM-DD)'); return }
    if (!validateDate(checkOut)) { setError('Invalid check-out date (use YYYY-MM-DD)'); return }
    if (checkOut <= checkIn) { setError('Check-out must be after check-in'); return }
    setLoading(true)
    try {
      const result = await getAvailableBerths(checkIn, checkOut)
      setBerths(result)
      setStep('availability')
    } catch {
      setError('Failed to fetch availability. Please try again.')
    }
    setLoading(false)
  }

  // ── Step 2: select a berth → confirmation screen ─────────────────────────
  const handleSelectBerth = (b: BerthOut) => {
    setSelected(b)
    setStep('confirmation')
  }

  // ── Step 3: confirm reservation ──────────────────────────────────────────
  const handleConfirm = async () => {
    if (!selected) return
    setConfirming(true)
    setError('')
    try {
      const res = await reserveBerth({
        berth_id: selected.id,
        check_in_date: checkIn,
        check_out_date: checkOut,
        notes: notes.trim() || undefined,
      })
      reset()
      onReserved(res)
    } catch (e: any) {
      const msg = e?.response?.data?.detail ?? 'Reservation failed. Please try again.'
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg))
    }
    setConfirming(false)
  }

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={handleClose}>
      <View style={s.overlay}>
        <View style={s.sheet}>
          {/* Header */}
          <View style={s.header}>
            <Text style={s.title}>⚓ Book a Berth</Text>
            <TouchableOpacity onPress={handleClose}>
              <Text style={s.closeBtn}>✕</Text>
            </TouchableOpacity>
          </View>

          {/* Step indicator */}
          <View style={s.steps}>
            {(['dates', 'availability', 'confirmation'] as Step[]).map((st, i) => (
              <View key={st} style={[s.stepDot, step === st && s.stepDotActive]} />
            ))}
          </View>

          <ScrollView showsVerticalScrollIndicator={false}>

            {/* ── STEP 1: Date Selection ───────────────────────────────── */}
            {step === 'dates' && (
              <View style={s.stepBody}>
                <Text style={s.sectionTitle}>Select Dates</Text>
                <Text style={s.label}>Check-in (YYYY-MM-DD)</Text>
                <TextInput
                  style={s.input}
                  value={checkIn}
                  onChangeText={setCheckIn}
                  placeholder="2026-06-01"
                  placeholderTextColor="#6b7280"
                  autoCorrect={false}
                />
                <Text style={s.label}>Check-out (YYYY-MM-DD)</Text>
                <TextInput
                  style={s.input}
                  value={checkOut}
                  onChangeText={setCheckOut}
                  placeholder="2026-06-07"
                  placeholderTextColor="#6b7280"
                  autoCorrect={false}
                />
                <Text style={s.label}>Notes (optional)</Text>
                <TextInput
                  style={[s.input, s.inputMulti]}
                  value={notes}
                  onChangeText={setNotes}
                  placeholder="Boat name, length, special requirements…"
                  placeholderTextColor="#6b7280"
                  multiline
                  numberOfLines={3}
                  maxLength={500}
                />
                {error ? <Text style={s.error}>{error}</Text> : null}
                <TouchableOpacity
                  style={[s.primaryBtn, loading && s.btnDisabled]}
                  onPress={handleCheckAvailability}
                  disabled={loading}
                >
                  {loading
                    ? <ActivityIndicator color="#fff" size="small" />
                    : <Text style={s.primaryBtnText}>Check Availability →</Text>}
                </TouchableOpacity>
              </View>
            )}

            {/* ── STEP 2: Berth List ───────────────────────────────────── */}
            {step === 'availability' && (
              <View style={s.stepBody}>
                <Text style={s.sectionTitle}>Available Berths</Text>
                <Text style={s.subtitle}>
                  {checkIn} → {checkOut}
                </Text>
                {berths.length === 0 ? (
                  <View style={s.emptyBox}>
                    <Text style={s.emptyIcon}>🚫</Text>
                    <Text style={s.emptyText}>No berths available for these dates.</Text>
                  </View>
                ) : (
                  berths.map((b) => (
                    <TouchableOpacity
                      key={b.id}
                      style={s.berthCard}
                      onPress={() => handleSelectBerth(b)}
                      activeOpacity={0.8}
                    >
                      <View style={s.berthCardLeft}>
                        <Text style={s.berthIcon}>⚓</Text>
                        <View>
                          <Text style={s.berthName}>{b.name}</Text>
                          {b.pedestal_id && (
                            <Text style={s.berthSub}>Pedestal {b.pedestal_id} · Electricity + Water</Text>
                          )}
                        </View>
                      </View>
                      <View style={s.freeBadge}>
                        <Text style={s.freeBadgeText}>Free</Text>
                      </View>
                    </TouchableOpacity>
                  ))
                )}
                <TouchableOpacity style={s.secondaryBtn} onPress={() => setStep('dates')}>
                  <Text style={s.secondaryBtnText}>← Change Dates</Text>
                </TouchableOpacity>
              </View>
            )}

            {/* ── STEP 3: Confirmation ─────────────────────────────────── */}
            {step === 'confirmation' && selected && (
              <View style={s.stepBody}>
                <Text style={s.sectionTitle}>Confirm Reservation</Text>
                <View style={s.confirmCard}>
                  <Row label="Berth" value={selected.name} />
                  {selected.pedestal_id && (
                    <Row label="Pedestal" value={`Pedestal ${selected.pedestal_id} (⚡ + 💧)`} />
                  )}
                  <Row label="Check-in" value={checkIn} />
                  <Row label="Check-out" value={checkOut} />
                  {notes ? <Row label="Notes" value={notes} /> : null}
                </View>
                {error ? <Text style={s.error}>{error}</Text> : null}
                <TouchableOpacity
                  style={[s.primaryBtn, confirming && s.btnDisabled]}
                  onPress={handleConfirm}
                  disabled={confirming}
                >
                  {confirming
                    ? <ActivityIndicator color="#fff" size="small" />
                    : <Text style={s.primaryBtnText}>✅ Confirm Reservation</Text>}
                </TouchableOpacity>
                <TouchableOpacity style={s.secondaryBtn} onPress={() => setStep('availability')}>
                  <Text style={s.secondaryBtnText}>← Back</Text>
                </TouchableOpacity>
              </View>
            )}

          </ScrollView>
        </View>
      </View>
    </Modal>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={s.row}>
      <Text style={s.rowLabel}>{label}</Text>
      <Text style={s.rowValue}>{value}</Text>
    </View>
  )
}

const s = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.65)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: '#1f2937',
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    maxHeight: '90%',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 24,
    paddingTop: 24,
    paddingBottom: 12,
  },
  title: { color: '#f9fafb', fontSize: 20, fontWeight: '800' },
  closeBtn: { color: '#9ca3af', fontSize: 22, paddingLeft: 12 },

  steps: {
    flexDirection: 'row',
    gap: 8,
    justifyContent: 'center',
    marginBottom: 16,
  },
  stepDot: {
    width: 8, height: 8, borderRadius: 4,
    backgroundColor: '#374151',
  },
  stepDotActive: { backgroundColor: '#3b82f6' },

  stepBody: { paddingHorizontal: 24, paddingBottom: 40, gap: 12 },

  sectionTitle: { color: '#f9fafb', fontSize: 16, fontWeight: '700', marginBottom: 4 },
  subtitle: { color: '#6b7280', fontSize: 13, marginTop: -4 },

  label: { color: '#9ca3af', fontSize: 13, marginTop: 4 },
  input: {
    backgroundColor: '#111827',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#374151',
    color: '#f9fafb',
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 14,
  },
  inputMulti: { minHeight: 80, textAlignVertical: 'top' },

  error: { color: '#f87171', fontSize: 13, textAlign: 'center' },

  primaryBtn: {
    backgroundColor: '#2563eb',
    borderRadius: 14,
    paddingVertical: 15,
    alignItems: 'center',
    marginTop: 8,
  },
  primaryBtnText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  btnDisabled: { opacity: 0.5 },

  secondaryBtn: {
    borderRadius: 14,
    paddingVertical: 13,
    alignItems: 'center',
    backgroundColor: '#374151',
  },
  secondaryBtnText: { color: '#d1d5db', fontWeight: '600', fontSize: 14 },

  emptyBox: { alignItems: 'center', paddingVertical: 30, gap: 10 },
  emptyIcon: { fontSize: 40 },
  emptyText: { color: '#6b7280', fontSize: 14, textAlign: 'center' },

  berthCard: {
    backgroundColor: '#111827',
    borderRadius: 14,
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderWidth: 1,
    borderColor: '#22c55e40',
  },
  berthCardLeft: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  berthIcon: { fontSize: 28 },
  berthName: { color: '#f9fafb', fontWeight: '700', fontSize: 14 },
  berthSub: { color: '#6b7280', fontSize: 12, marginTop: 2 },
  freeBadge: {
    backgroundColor: '#14532d',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderWidth: 1,
    borderColor: '#16a34a',
  },
  freeBadgeText: { color: '#4ade80', fontWeight: '700', fontSize: 12 },

  confirmCard: {
    backgroundColor: '#111827',
    borderRadius: 14,
    padding: 16,
    borderWidth: 1,
    borderColor: '#374151',
    gap: 10,
  },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  rowLabel: { color: '#6b7280', fontSize: 13, flex: 1 },
  rowValue: { color: '#f9fafb', fontSize: 13, fontWeight: '600', flex: 2, textAlign: 'right' },
})
