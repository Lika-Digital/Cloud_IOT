import { useState, useEffect, useRef } from 'react'
import {
  View, Text, TouchableOpacity, StyleSheet, Modal,
  ActivityIndicator, ScrollView,
} from 'react-native'
import { startSession } from '../api/sessions'
import { getPedestalStatus, type PedestalStatus } from '../api/pedestals'
import { useSessionStore } from '../store/sessionStore'
import { PedestalDiagram, type SelectionType } from './PedestalDiagram'

interface Props {
  visible: boolean
  onClose: () => void
}

export function StartSessionModal({ visible, onClose }: Props) {
  const [pedestals, setPedestals] = useState<PedestalStatus[]>([])
  const [selectedPedestal, setSelectedPedestal] = useState<PedestalStatus | null>(null)
  const [selType, setSelType] = useState<SelectionType>(null)
  const [selSocketId, setSelSocketId] = useState<number | null>(null)
  const [loadingPedestals, setLoadingPedestals] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const { setActiveSession } = useSessionStore()
  const inFlight = useRef(false)

  // Load pedestal status whenever modal opens
  useEffect(() => {
    if (!visible) return
    setError('')
    setSelType(null)
    setSelSocketId(null)
    setSelectedPedestal(null)
    setLoadingPedestals(true)
    getPedestalStatus()
      .then((data) => {
        setPedestals(data)
        if (data.length === 1) setSelectedPedestal(data[0])
      })
      .catch(() => setError('Could not load pedestal status'))
      .finally(() => setLoadingPedestals(false))
  }, [visible])

  const handleSelectSocket = (socketId: number) => {
    setSelType('electricity')
    setSelSocketId(socketId)
  }

  const handleSelectWater = () => {
    setSelType('water')
    setSelSocketId(null)
  }

  const handleStart = async () => {
    if (!selectedPedestal || !selType) return
    if (selType === 'electricity' && selSocketId === null) return
    if (inFlight.current) return
    inFlight.current = true
    setSubmitting(true)
    setError('')
    try {
      const session = await startSession({
        pedestal_id: selectedPedestal.id,
        type: selType,
        socket_id: selType === 'electricity' ? selSocketId! : undefined,
      })
      setActiveSession({
        id: session.id,
        pedestal_id: session.pedestal_id,
        socket_id: session.socket_id,
        type: session.type as 'electricity' | 'water',
        status: session.status,
        started_at: session.started_at,
        customer_id: session.customer_id,
      })
      onClose()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Failed to start session')
    } finally {
      inFlight.current = false
      setSubmitting(false)
    }
  }

  const canStart = selectedPedestal !== null && selType !== null &&
    (selType === 'water' || selSocketId !== null)

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.overlay}>
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <Text style={styles.title}>Start Session</Text>

          {loadingPedestals ? (
            <ActivityIndicator color="#60a5fa" style={{ marginVertical: 40 }} />
          ) : (
            <ScrollView showsVerticalScrollIndicator={false} bounces={false}>
              {/* ── Pedestal selector (shown only if >1 pedestal) ───────── */}
              {pedestals.length > 1 && (
                <View style={styles.pedestalSelector}>
                  <Text style={styles.selectorLabel}>Select pedestal</Text>
                  <View style={styles.pedestalBtns}>
                    {pedestals.map((p) => (
                      <TouchableOpacity
                        key={p.id}
                        style={[styles.pedestalBtn, selectedPedestal?.id === p.id && styles.pedestalBtnActive]}
                        onPress={() => {
                          setSelectedPedestal(p)
                          setSelType(null)
                          setSelSocketId(null)
                        }}
                      >
                        <Text style={[styles.pedestalBtnText, selectedPedestal?.id === p.id && styles.pedestalBtnTextActive]}>
                          {p.name}
                        </Text>
                        {p.location ? (
                          <Text style={styles.pedestalBtnSub}>{p.location}</Text>
                        ) : null}
                      </TouchableOpacity>
                    ))}
                  </View>
                </View>
              )}

              {/* ── Instruction ─────────────────────────────────────────── */}
              {selectedPedestal && (
                <Text style={styles.instruction}>
                  Tap a socket or the water tap to select
                </Text>
              )}

              {/* ── Visual pedestal diagram ──────────────────────────────── */}
              {selectedPedestal ? (
                <PedestalDiagram
                  pedestalName={selectedPedestal.name}
                  location={selectedPedestal.location}
                  occupiedSockets={selectedPedestal.occupied_sockets}
                  waterOccupied={selectedPedestal.water_occupied}
                  selectedType={selType}
                  selectedSocketId={selSocketId}
                  onSelectSocket={handleSelectSocket}
                  onSelectWater={handleSelectWater}
                />
              ) : pedestals.length === 0 ? (
                <Text style={styles.empty}>No pedestals available.</Text>
              ) : null}

              {error ? <Text style={styles.error}>{error}</Text> : null}

              {/* ── Confirm button ──────────────────────────────────────── */}
              <TouchableOpacity
                style={[styles.confirmBtn, !canStart && styles.confirmBtnDisabled]}
                onPress={handleStart}
                disabled={!canStart || submitting}
              >
                {submitting ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <Text style={styles.confirmText}>
                    {!selType
                      ? 'Select a socket above'
                      : selType === 'electricity'
                        ? `Request Socket ${selSocketId} — ${selectedPedestal?.name}`
                        : `Request Water — ${selectedPedestal?.name}`}
                  </Text>
                )}
              </TouchableOpacity>

              <TouchableOpacity style={styles.cancelBtn} onPress={onClose}>
                <Text style={styles.cancelText}>Cancel</Text>
              </TouchableOpacity>
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  )
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: '#111827',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    padding: 20,
    paddingBottom: 36,
    maxHeight: '90%',
  },
  handle: {
    width: 40, height: 4, backgroundColor: '#374151',
    borderRadius: 2, alignSelf: 'center', marginBottom: 12,
  },
  title: {
    color: '#fff', fontSize: 20, fontWeight: '700',
    textAlign: 'center', marginBottom: 16,
  },

  // Pedestal selector
  pedestalSelector: { marginBottom: 14 },
  selectorLabel: { color: '#9ca3af', fontSize: 12, fontWeight: '600', marginBottom: 8 },
  pedestalBtns: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  pedestalBtn: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 10,
    backgroundColor: '#1f2937', borderWidth: 1, borderColor: '#374151',
  },
  pedestalBtnActive: { backgroundColor: '#1e3a5f', borderColor: '#3b82f6' },
  pedestalBtnText: { color: '#9ca3af', fontWeight: '600', fontSize: 14 },
  pedestalBtnTextActive: { color: '#60a5fa' },
  pedestalBtnSub: { color: '#6b7280', fontSize: 11, marginTop: 2 },

  instruction: {
    color: '#6b7280', fontSize: 13, textAlign: 'center',
    marginBottom: 12, fontStyle: 'italic',
  },
  empty: { color: '#6b7280', textAlign: 'center', marginVertical: 30 },
  error: {
    color: '#ef4444', fontSize: 13, textAlign: 'center',
    marginTop: 12, backgroundColor: '#1f1515', borderRadius: 8, padding: 10,
  },

  confirmBtn: {
    backgroundColor: '#2563eb', paddingVertical: 15,
    borderRadius: 12, alignItems: 'center', marginTop: 16,
  },
  confirmBtnDisabled: { backgroundColor: '#1e3050', opacity: 0.7 },
  confirmText: { color: '#fff', fontWeight: '700', fontSize: 15 },

  cancelBtn: { paddingVertical: 12, alignItems: 'center' },
  cancelText: { color: '#6b7280', fontSize: 15 },
})
