import { View, Text, TouchableOpacity, StyleSheet } from 'react-native'

export type SelectionType = 'electricity' | 'water' | null

interface Props {
  pedestalName: string
  location: string | null
  occupiedSockets: number[]   // socket IDs currently in use (pending/active)
  waterOccupied: boolean
  selectedType: SelectionType
  selectedSocketId: number | null
  onSelectSocket: (id: number) => void
  onSelectWater: () => void
}

export function PedestalDiagram({
  pedestalName,
  location,
  occupiedSockets,
  waterOccupied,
  selectedType,
  selectedSocketId,
  onSelectSocket,
  onSelectWater,
}: Props) {
  return (
    <View style={styles.pedestal}>
      {/* ── Header ──────────────────────────────────────────────── */}
      <View style={styles.header}>
        <Text style={styles.headerLabel}>MARINA PEDESTAL</Text>
        <Text style={styles.headerName}>{pedestalName}</Text>
        {location ? <Text style={styles.headerLocation}>{location}</Text> : null}
      </View>

      {/* ── Electricity section ──────────────────────────────────── */}
      <View style={styles.section}>
        <View style={styles.sectionTitleRow}>
          <View style={styles.sectionBar} />
          <Text style={styles.sectionLabel}>⚡  ELECTRICITY</Text>
          <View style={styles.sectionBar} />
        </View>

        <View style={styles.socketGrid}>
          {[1, 2, 3, 4].map((id) => {
            const occupied = occupiedSockets.includes(id)
            const selected = selectedType === 'electricity' && selectedSocketId === id
            return (
              <TouchableOpacity
                key={id}
                style={[
                  styles.socket,
                  occupied && styles.socketOccupied,
                  selected && styles.socketSelected,
                  !occupied && !selected && styles.socketFree,
                ]}
                onPress={() => onSelectSocket(id)}
                disabled={occupied}
                activeOpacity={0.75}
              >
                {/* Socket face — schematic of a CEE plug */}
                <View style={[styles.socketFace, occupied ? styles.faceDim : selected ? styles.faceSelected : styles.faceFree]}>
                  <View style={styles.pinsRow}>
                    <View style={[styles.pin, occupied ? styles.pinDim : styles.pinActive]} />
                    <View style={[styles.pin, occupied ? styles.pinDim : styles.pinActive]} />
                  </View>
                  <View style={[styles.pin, styles.pinGnd, occupied ? styles.pinDim : styles.pinActive]} />
                </View>

                <Text style={[styles.socketNum, occupied ? styles.textDim : selected ? styles.textSelected : styles.textFree]}>
                  {id}
                </Text>
                <Text style={[styles.socketStatus, occupied ? styles.statusOccupied : selected ? styles.statusSelected : styles.statusFree]}>
                  {occupied ? 'IN USE' : selected ? 'SELECTED' : 'FREE'}
                </Text>
              </TouchableOpacity>
            )
          })}
        </View>
      </View>

      {/* ── Divider ──────────────────────────────────────────────── */}
      <View style={styles.divider} />

      {/* ── Water section ────────────────────────────────────────── */}
      <View style={styles.section}>
        <View style={styles.sectionTitleRow}>
          <View style={styles.sectionBar} />
          <Text style={styles.sectionLabel}>💧  WATER</Text>
          <View style={styles.sectionBar} />
        </View>

        <TouchableOpacity
          style={[
            styles.waterBtn,
            waterOccupied && styles.waterOccupied,
            selectedType === 'water' && !waterOccupied && styles.waterSelected,
            !waterOccupied && selectedType !== 'water' && styles.waterFree,
          ]}
          onPress={onSelectWater}
          disabled={waterOccupied}
          activeOpacity={0.75}
        >
          {/* Water tap schematic */}
          <View style={styles.tapIcon}>
            <View style={[styles.tapBody, waterOccupied ? styles.tapDim : selectedType === 'water' ? styles.tapSel : styles.tapNormal]} />
            <View style={[styles.tapHandle, waterOccupied ? styles.tapDim : selectedType === 'water' ? styles.tapSel : styles.tapNormal]} />
            <View style={[styles.tapSpout, waterOccupied ? styles.tapDim : selectedType === 'water' ? styles.tapSel : styles.tapNormal]} />
          </View>
          <View style={styles.waterInfo}>
            <Text style={[styles.waterLabel, waterOccupied ? styles.textDim : selectedType === 'water' ? styles.textSelected : styles.textFree]}>
              Fresh Water
            </Text>
            <Text style={[styles.waterStatus, waterOccupied ? styles.statusOccupied : selectedType === 'water' ? styles.statusSelected : styles.statusFree]}>
              {waterOccupied ? 'IN USE' : selectedType === 'water' ? 'SELECTED' : 'FREE'}
            </Text>
          </View>
        </TouchableOpacity>
      </View>

      {/* ── Footer legend ─────────────────────────────────────────── */}
      <View style={styles.legend}>
        <LegendDot color="#22c55e" label="Free" />
        <LegendDot color="#3b82f6" label="Selected" />
        <LegendDot color="#ef4444" label="In Use" />
      </View>
    </View>
  )
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <View style={styles.legendItem}>
      <View style={[styles.legendDot, { backgroundColor: color }]} />
      <Text style={styles.legendLabel}>{label}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  pedestal: {
    backgroundColor: '#1a2332',
    borderRadius: 16,
    borderWidth: 2,
    borderColor: '#2d4a6e',
    overflow: 'hidden',
  },

  // Header
  header: {
    backgroundColor: '#0f1d2e',
    padding: 14,
    alignItems: 'center',
    borderBottomWidth: 1,
    borderBottomColor: '#2d4a6e',
  },
  headerLabel: { color: '#4b7bb5', fontSize: 10, fontWeight: '700', letterSpacing: 2 },
  headerName: { color: '#e2f0ff', fontSize: 18, fontWeight: '800', marginTop: 2 },
  headerLocation: { color: '#6b8fb5', fontSize: 12, marginTop: 2 },

  // Sections
  section: { padding: 16 },
  sectionTitleRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 14, gap: 8 },
  sectionBar: { flex: 1, height: 1, backgroundColor: '#2d4a6e' },
  sectionLabel: { color: '#7fa8d4', fontSize: 12, fontWeight: '700', letterSpacing: 1 },

  divider: { height: 1, backgroundColor: '#2d4a6e', marginHorizontal: 16 },

  // Socket grid
  socketGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  socket: {
    width: '47%',
    borderRadius: 12,
    borderWidth: 2,
    padding: 12,
    alignItems: 'center',
    gap: 6,
  },
  socketFree:     { borderColor: '#22c55e', backgroundColor: '#0d2218' },
  socketSelected: { borderColor: '#3b82f6', backgroundColor: '#0d1e3a' },
  socketOccupied: { borderColor: '#374151', backgroundColor: '#111827', opacity: 0.6 },

  // Socket face (plug schematic)
  socketFace: {
    width: 44,
    height: 44,
    borderRadius: 22,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
  },
  faceFree:     { borderColor: '#22c55e', backgroundColor: '#0a1f15' },
  faceSelected: { borderColor: '#3b82f6', backgroundColor: '#0a1428' },
  faceDim:      { borderColor: '#374151', backgroundColor: '#1a1a1a' },
  pinsRow: { flexDirection: 'row', gap: 10 },
  pin: { width: 5, height: 10, borderRadius: 2 },
  pinGnd: { width: 5, height: 10, borderRadius: 2 },
  pinActive: { backgroundColor: '#9ca3af' },
  pinDim:    { backgroundColor: '#374151' },

  socketNum:    { fontSize: 20, fontWeight: '800' },
  socketStatus: { fontSize: 9, fontWeight: '700', letterSpacing: 1 },

  textFree:     { color: '#22c55e' },
  textSelected: { color: '#60a5fa' },
  textDim:      { color: '#4b5563' },
  statusFree:      { color: '#16a34a' },
  statusSelected:  { color: '#2563eb' },
  statusOccupied:  { color: '#dc2626' },

  // Water button
  waterBtn: {
    borderRadius: 12,
    borderWidth: 2,
    padding: 16,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 16,
  },
  waterFree:     { borderColor: '#22c55e', backgroundColor: '#0d2218' },
  waterSelected: { borderColor: '#3b82f6', backgroundColor: '#0d1e3a' },
  waterOccupied: { borderColor: '#374151', backgroundColor: '#111827', opacity: 0.6 },

  // Tap schematic
  tapIcon: { alignItems: 'center', width: 36, gap: 2 },
  tapHandle: { width: 28, height: 8, borderRadius: 4 },
  tapBody:   { width: 20, height: 20, borderRadius: 4 },
  tapSpout:  { width: 14, height: 8, borderRadius: 4, marginLeft: 10 },
  tapNormal: { backgroundColor: '#9ca3af' },
  tapSel:    { backgroundColor: '#60a5fa' },
  tapDim:    { backgroundColor: '#374151' },

  waterInfo: { flex: 1 },
  waterLabel:  { fontSize: 15, fontWeight: '700' },
  waterStatus: { fontSize: 10, fontWeight: '700', letterSpacing: 1, marginTop: 2 },

  // Legend
  legend: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 20,
    paddingVertical: 12,
    borderTopWidth: 1,
    borderTopColor: '#2d4a6e',
    backgroundColor: '#0f1d2e',
  },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  legendDot:  { width: 8, height: 8, borderRadius: 4 },
  legendLabel: { color: '#6b8fb5', fontSize: 11 },
})
