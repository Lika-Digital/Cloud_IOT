import { useState } from 'react'
import {
  View, Text, TouchableOpacity, StyleSheet, Image,
  LayoutChangeEvent, Alert,
} from 'react-native'
import { useTheme } from '../hooks/useTheme'

export type SelectionType = 'electricity' | 'water' | null

interface Props {
  pedestalName: string
  location: string | null
  occupiedSockets: number[]
  waterOccupied: boolean
  selectedType: SelectionType
  selectedSocketId: number | null
  onSelectSocket: (id: number) => void
  onSelectWater: () => void
  assignedSocketId?: number | null  // pilot mode: only this socket is selectable
}

interface Zone { leftPct?: number; rightPct?: number; topPct: number }
interface ElecZone extends Zone { id: number }
interface WaterZone extends Zone { id: string }

// Zone positions as fractions (matching frontend PedestalView.tsx SOCKET_ZONES)
// left/rightPct are from the respective edge; topPct from top
const ELECTRICITY_ZONES: ElecZone[] = [
  { id: 1, leftPct: 0.03,  topPct: 0.37 },
  { id: 2, leftPct: 0.03,  topPct: 0.52 },
  { id: 3, rightPct: 0.03, topPct: 0.37 },
  { id: 4, rightPct: 0.03, topPct: 0.52 },
]

const WATER_ZONES: WaterZone[] = [
  { id: 'wl', leftPct: 0.08,  topPct: 0.84 },
  { id: 'wr', rightPct: 0.08, topPct: 0.84 },
]

const IMG_HEIGHT = 320
const SOCK_R = 24   // circle radius for sockets
const WATER_R = 20  // circle radius for water

export function PedestalDiagram({
  pedestalName,
  location,
  occupiedSockets,
  waterOccupied,
  selectedType,
  selectedSocketId,
  onSelectSocket,
  onSelectWater,
  assignedSocketId,
}: Props) {
  const t = useTheme()
  const [imgW, setImgW] = useState(0)

  const onLayout = (e: LayoutChangeEvent) => setImgW(e.nativeEvent.layout.width)

  const showHelp = () => Alert.alert(
    'Pedestal Guide',
    'Tap a numbered circle on the pedestal image to select an electricity socket.\n\nTap 💧 to select a water connection.\n\n🟢 Green = free to use\n🔵 Blue = your selection\n🔴 Red = currently in use by another customer\n\nAfter selecting, tap the Request button below.',
  )

  const getX = (zone: { leftPct?: number; rightPct?: number }, r: number) => {
    if (imgW === 0) return 0
    if (zone.leftPct !== undefined) return zone.leftPct * imgW - r
    return imgW - (zone.rightPct ?? 0) * imgW - r
  }

  const getY = (topPct: number, r: number) => topPct * IMG_HEIGHT - r

  return (
    <View style={[styles.pedestal, { backgroundColor: t.cardAlt, borderColor: t.border }]}>
      {/* ── Header ─────────────────────────────────────────────── */}
      <View style={[styles.header, { backgroundColor: t.card, borderBottomColor: t.border }]}>
        <View style={styles.headerRow}>
          <View style={{ flex: 1 }}>
            <Text style={[styles.headerLabel, { color: t.textMuted }]}>MARINA PEDESTAL</Text>
            <Text style={[styles.headerName, { color: t.textPrimary }]}>{pedestalName}</Text>
            {location ? <Text style={[styles.headerLoc, { color: t.textMuted }]}>{location}</Text> : null}
          </View>
          <TouchableOpacity
            style={[styles.helpBtn, { backgroundColor: t.accentBg }]}
            onPress={showHelp}
          >
            <Text style={[styles.helpBtnTxt, { color: t.accentLight }]}>?</Text>
          </TouchableOpacity>
        </View>
        <Text style={[styles.hint, { color: t.textMuted }]}>
          Tap a socket circle or water icon on the pedestal
        </Text>
      </View>

      {/* ── Pedestal image with clickable zones ──────────────── */}
      <View style={styles.imgContainer} onLayout={onLayout}>
        <Image
          source={require('../../assets/pedestal.jpg')}
          style={styles.img}
          resizeMode="stretch"
        />

        {imgW > 0 && (
          <>
            {/* Electricity socket circles */}
            {ELECTRICITY_ZONES.map((zone) => {
              const occupied = occupiedSockets.includes(zone.id)
              const selected = selectedType === 'electricity' && selectedSocketId === zone.id
              // In pilot mode, non-assigned sockets are locked (not just occupied)
              const locked = assignedSocketId != null && zone.id !== assignedSocketId
              const x = getX(zone, SOCK_R)
              const y = getY(zone.topPct, SOCK_R)

              const bg = occupied || locked ? '#1c1917' : selected ? '#1e3a5f' : '#14532d'
              const border = occupied || locked ? '#57534e' : selected ? '#3b82f6' : '#22c55e'
              const color = occupied || locked ? '#78716c' : selected ? '#60a5fa' : '#4ade80'

              return (
                <TouchableOpacity
                  key={zone.id}
                  style={[
                    styles.circle,
                    {
                      left: x,
                      top: y,
                      width: SOCK_R * 2,
                      height: SOCK_R * 2,
                      borderRadius: SOCK_R,
                      backgroundColor: bg,
                      borderColor: border,
                      opacity: occupied || locked ? 0.5 : 1,
                    },
                  ]}
                  onPress={() => !occupied && !locked && onSelectSocket(zone.id)}
                  disabled={occupied || locked}
                  activeOpacity={0.7}
                >
                  <Text style={[styles.circleNum, { color }]}>{zone.id}</Text>
                </TouchableOpacity>
              )
            })}

            {/* Water circles */}
            {WATER_ZONES.map((zone) => {
              const selected = selectedType === 'water'
              const x = getX(zone, WATER_R)
              const y = getY(zone.topPct, WATER_R)

              const bg = waterOccupied ? '#1c1917' : selected ? '#1e3a5f' : '#164e63'
              const border = waterOccupied ? '#57534e' : selected ? '#3b82f6' : '#06b6d4'

              return (
                <TouchableOpacity
                  key={zone.id}
                  style={[
                    styles.circle,
                    {
                      left: x,
                      top: y,
                      width: WATER_R * 2,
                      height: WATER_R * 2,
                      borderRadius: WATER_R,
                      backgroundColor: bg,
                      borderColor: border,
                      opacity: waterOccupied ? 0.65 : 1,
                    },
                  ]}
                  onPress={() => !waterOccupied && onSelectWater()}
                  disabled={waterOccupied}
                  activeOpacity={0.7}
                >
                  <Text style={{ fontSize: 13 }}>💧</Text>
                </TouchableOpacity>
              )
            })}
          </>
        )}
      </View>

      {/* ── Selection badge ──────────────────────────────────── */}
      <View style={[styles.selRow, { borderTopColor: t.border }]}>
        {selectedType === null ? (
          <Text style={[styles.selHint, { color: t.textMuted }]}>Nothing selected — tap above</Text>
        ) : selectedType === 'electricity' ? (
          <View style={[styles.badge, { backgroundColor: '#1e3a5f', borderColor: '#3b82f6' }]}>
            <Text style={{ color: '#60a5fa', fontWeight: '700', fontSize: 13 }}>
              ⚡ Socket {selectedSocketId} selected
            </Text>
          </View>
        ) : (
          <View style={[styles.badge, { backgroundColor: '#164e63', borderColor: '#06b6d4' }]}>
            <Text style={{ color: '#67e8f9', fontWeight: '700', fontSize: 13 }}>
              💧 Water tap selected
            </Text>
          </View>
        )}
      </View>

      {/* ── Legend ───────────────────────────────────────────── */}
      <View style={[styles.legend, { backgroundColor: t.card, borderTopColor: t.border }]}>
        {[['#22c55e', 'Free'], ['#3b82f6', 'Selected'], ['#ef4444', 'In Use']].map(([color, label]) => (
          <View key={label} style={styles.legendItem}>
            <View style={[styles.dot, { backgroundColor: color }]} />
            <Text style={[styles.legendTxt, { color: t.textMuted }]}>{label}</Text>
          </View>
        ))}
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  pedestal: { borderRadius: 16, borderWidth: 1.5, overflow: 'hidden' },

  header: { padding: 14, borderBottomWidth: 1 },
  headerRow: { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 4 },
  headerLabel: { fontSize: 10, fontWeight: '700', letterSpacing: 2 },
  headerName: { fontSize: 17, fontWeight: '800', marginTop: 1 },
  headerLoc: { fontSize: 11, marginTop: 1 },
  hint: { fontSize: 12, fontStyle: 'italic' },

  helpBtn: { width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  helpBtnTxt: { fontSize: 15, fontWeight: '800' },

  imgContainer: {
    width: '100%',
    height: IMG_HEIGHT,
    position: 'relative',
    overflow: 'hidden',
  },
  img: {
    position: 'absolute',
    top: 0, left: 0,
    width: '100%',
    height: IMG_HEIGHT,
  },

  circle: {
    position: 'absolute',
    borderWidth: 2.5,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.5,
    shadowRadius: 3,
    elevation: 5,
  },
  circleNum: { fontSize: 16, fontWeight: '900' },

  selRow: { paddingVertical: 10, paddingHorizontal: 14, borderTopWidth: 1, alignItems: 'center' },
  selHint: { fontSize: 12, fontStyle: 'italic' },
  badge: { paddingHorizontal: 16, paddingVertical: 7, borderRadius: 20, borderWidth: 1 },

  legend: {
    flexDirection: 'row', justifyContent: 'center', gap: 20,
    paddingVertical: 10, borderTopWidth: 1,
  },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  legendTxt: { fontSize: 11 },
})
